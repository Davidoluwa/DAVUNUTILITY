-- PlayerCareer.lua
-- ============================================================
-- Player Career state manager.
--
-- Player Career is NOT a new mode on its own — it is a STATE on top
-- of the existing career-mode framework. It reuses the same cache
-- (TeamCachedData / fifaSquad), the same match simulator
-- (MatchSimulator:simulateDayMatches), the same transfer engine
-- (AITransfers:batchTransfers), the same date-advance loop
-- (MatchSelect:NoMatch / advanceDateStep) and the same save/load
-- pipeline (Serializer / LoadSave).
--
-- The ONLY things this module owns:
--   1. AI manager squad selection for the user's team each matchday
--      (reuses the existing pickSquad algorithm from StartMatch.lua,
--       refactored into a standalone helper so it can run before
--       the pre-match screen is constructed).
--   2. "Can the user play today?" gate — true only if the user's
--      controlled player is in the AI manager's starting XI.
--   3. Transfer-offer scan for the user's player — reads the same
--      sessionVars.transferOffers table that AITransfers.lua already
--      populates; surfaces offers for the user's player to the user,
--      and auto-resolves offers for the user's teammates (the AI
--      manager handles the rest of the squad).
--
-- This module never touches Manager / Tournament career code paths
-- — every public method is a no-op when InPlayerCareerMode is false.
-- ============================================================

local sessionVars, FCPopup = ...
local PlayerCareer = {}

-- ── Constructor ─────────────────────────────────────────────────────────────
-- services MUST contain SquadManagementService (for SetCurrentPlayerLineup)
-- and TacticsService (for formation lookups). Both are already wired up by
-- MatchSelect.lua's constructor and are passed straight through.
function PlayerCareer:new(init)
    local o = init or {}
    setmetatable(o, self)
    self.__index = self
    o.services = init.services or {}
    o.nav      = init.nav
    o.loc      = init.loc
    o.FCPopup  = FCPopup:new({ nav = init.nav })
    return o
end

-- ── Mode guard ──────────────────────────────────────────────────────────────
-- Every public method calls this first. If we're not in player career mode,
-- the method returns nil/false immediately — zero impact on manager/tournament.
local function isActive()
    return sessionVars.get("InPlayerCareerMode") == true
end

-- ── User's controlled player helpers ────────────────────────────────────────
function PlayerCareer:getPlayerID()
    return sessionVars.get("PlayerCareerPlayerID")
end

function PlayerCareer:setPlayerID(cardID)
    sessionVars.set("PlayerCareerPlayerID", cardID)
end

function PlayerCareer:getPlayerTeamID()
    -- The user's player is always on currentSelectedTeamID at career start.
    -- After a transfer (accept-offer), currentSelectedTeamID is updated to
    -- the buying club, keeping this lookup correct.
    return currentSelectedTeamID
end

-- ── AI Manager squad selection ──────────────────────────────────────────────
-- Refactored from StartMatch:pickSquad (Screens/StartMatch/StartMatch.lua).
-- The algorithm is identical: group players by position, weighted-random pick
-- for each starter slot, fill bench with highest-rated remaining, fill
-- reserves with the rest. The ONLY differences are:
--   1. Reads from the cache (getCachedTeamPlayers) instead of the service
--      so the user's transfers/loans are respected.
--   2. Writes the reordered squad back to BOTH the cache and the service
--      (so the FIFA match engine sees the right XI when the user plays).
--   3. Returns the array of 11 starter CARD_IDs so the caller can check
--      whether the user's player is in the XI without a second scan.
--
-- Strength mode is chosen per-matchday from a weighted-random draw driven by
-- the strength gap between our team and today's opponent (see pickSquadMode
-- below) — NOT a hardcoded "always balanced". The user's own team is treated
-- exactly like any AI manager would treat their own team.
local POS_GROUP = {
    GK=1, CB=2, LB=2, RB=2, LWB=2, RWB=2,
    CM=3, CDM=3, CAM=3, LM=3, RM=3,
    ST=4, CF=4, LW=4, RW=4, LF=4, RF=4,
}

-- ── Team strength lookup ─────────────────────────────────────────────────
-- Prefers the league's precomputed TeamStrength table (attack/midfield/
-- defense, populated by TeamData:updateTeamsStrength — the same numbers the
-- match engine itself uses to rate a team). Falls back to the average rating
-- of the team's own cached players if that table isn't available yet (e.g.
-- very first matchday of a brand-new save).
local function teamOverall(teamID)
    if not teamID then return 50 end
    local ts = sessionVars.get("TeamStrength")
    local t  = ts and ts[teamID]
    if t and (t.attack or t.midfield or t.defense) then
        return ((t.attack or 50) + (t.midfield or 50) + (t.defense or 50)) / 3
    end
    local squad = getCachedTeamPlayers(teamID) or {}
    local count = math.min(#squad, 18)
    if count == 0 then return 50 end
    local sum = 0
    for i = 1, count do sum = sum + (squad[i].rating or 50) end
    return sum / count
end

-- ── Opponent-aware, randomised starting-XI mode ─────────────────────────
-- Returns "strong", "balanced", or "weak" for the starting XI. This is a
-- weighted random draw, not an if/else ladder with fixed outcomes:
--   * Tough opponent (they're clearly stronger) → heavily weighted to
--     "strong", but never 100% — an AI manager can still gamble.
--   * Evenly matched / we're only slightly better → mostly a full-strength
--     or balanced XI.
--   * We're clearly / hugely better → rotation ("weak") becomes more likely,
--     but fielding the strong side stays the plurality outcome even against
--     the weakest sides. Wholesale rotation is the exception, not the rule —
--     exactly like a real manager who mostly plays to win even against
--     minnows, and only occasionally rests his best players.
local function pickSquadMode(gap)
    local weights
    if gap <= -8 then                  -- tough opponent: they're notably stronger
        weights = { strong = 0.72, balanced = 0.24, weak = 0.04 }
    elseif gap <= 3 then                -- evenly matched
        weights = { strong = 0.55, balanced = 0.38, weak = 0.07 }
    elseif gap <= 10 then                -- we're clearly the better side
        weights = { strong = 0.45, balanced = 0.38, weak = 0.17 }
    else                                  -- huge mismatch in our favour
        weights = { strong = 0.38, balanced = 0.34, weak = 0.28 }
    end

    local r, cum = math.random(), 0
    for _, mode in ipairs({ "strong", "balanced", "weak" }) do
        cum = cum + weights[mode]
        if r <= cum then return mode end
    end
    return "balanced"
end

function PlayerCareer:pickAISquad(teamID, opponentTeamID)
    if not isActive() then return nil end
    if not teamID then return nil end

    -- Idempotent per matchday: once the AI manager has picked today's XI for
    -- this team, re-entering the pre-match screen (reload, popping in/out of
    -- the squad hub, etc.) must not reshuffle it — a real manager doesn't
    -- change his team sheet every time you glance at it.
    local today   = GLOBAL_DATE_PLACEHOLDER
    local thisKey = tostring(today) .. "|" .. tostring(teamID)
    if sessionVars.get("PlayerCareerSquadPickKey") == thisKey then
        local cached = getCachedTeamPlayers(teamID) or {}
        local starterIDs = {}
        for i = 1, math.min(11, #cached) do
            starterIDs[#starterIDs + 1] = cached[i].CARD_ID
        end
        return starterIDs
    end

    local players = getCachedTeamPlayers(teamID) or {}
    local n = #players
    if n == 0 then return nil end

    -- ── Suspension / injury exclusion ───────────────────────────────────
    -- isSuspended[leagueID][CARD_ID] == 1 (red-card suspension) or 2
    -- (injury) — either way the player can never be in the starting XI.
    -- They're also kept off the bench UNLESS the club doesn't have enough
    -- fit players to fill a normal 11 + 7 squad, in which case the AI
    -- manager has no choice but to name them among the substitutes.
    local leagueID   = sessionVars.get("currentUserLeagueID")
    local suspTable  = sessionVars.get("isSuspended") or {}
    local leagueSusp = (leagueID and suspTable[leagueID]) or {}
    local function isUnavailable(p)
        local v = p and leagueSusp[p.CARD_ID]
        return v == 1 or v == 2
    end
    -- Unavailable = banned from the competition of today's match (not of the user's league), or
    -- injured wherever it is filed.
    do
        local S = rawget(_G, "PRISM_SUSP")
        if S and S.unavailable then
            local comp = (S.todayComp and S.todayComp(teamID)) or leagueID
            local base = isUnavailable
            isUnavailable = function(p)
                local ok, v = pcall(S.unavailable, p and p.CARD_ID, comp)
                if ok then return v end
                return base(p)
            end
        end
    end

    local eligible, unavailable = {}, {}
    for i = 1, n do
        local p = players[i]
        if isUnavailable(p) then
            unavailable[#unavailable + 1] = p
        else
            eligible[#eligible + 1] = p
        end
    end
    table.sort(unavailable, function(a, b) return (a.rating or 0) > (b.rating or 0) end)

    -- ── Opponent-strength-aware mode for the starting XI ────────────────
    local gap  = teamOverall(teamID) - teamOverall(opponentTeamID)
    local mode = pickSquadMode(gap)

    -- Group ELIGIBLE (fit) players by position only — a suspended/injured
    -- player must never re-enter through a "no more of this position left"
    -- fallback.
    local byPos, posOrder = {}, {}
    for i = 1, #eligible do
        local p   = eligible[i]
        local pos = p.position
        if not byPos[pos] then byPos[pos] = {}; posOrder[#posOrder + 1] = pos end
        byPos[pos][#byPos[pos] + 1] = p
    end
    for _, pos in ipairs(posOrder) do
        table.sort(byPos[pos], function(a, b) return (a.rating or 0) > (b.rating or 0) end)
    end
    local posCounts = {}
    for _, pos in ipairs(posOrder) do posCounts[pos] = #byPos[pos] end

    local function pickIdx(pos, m)
        local count = posCounts[pos]
        if not count or count == 0 then return nil end
        local list, totalW, weights = byPos[pos], 0, {}
        for i = 1, count do
            local r = list[i].rating or 50
            local w = m == "strong" and math.exp((r - 60) * 0.2)
                   or m == "weak"   and math.exp((100 - r) * 0.2)
                   or 1.0
            weights[i] = w; totalW = totalW + w
        end
        local rnd, cum = math.random() * totalW, 0
        for i = 1, count do
            cum = cum + weights[i]
            if rnd <= cum then return i end
        end
        return 1
    end

    local function removeAt(pos, idx)
        if not idx then return end
        local list  = byPos[pos]
        local count = posCounts[pos]
        for i = idx, count - 1 do list[i] = list[i + 1] end
        list[count] = nil; posCounts[pos] = count - 1
    end

    -- Walks the ELIGIBLE-only array for its position template, so a
    -- suspended/injured player can never come back via the "orig" fallback.
    local function selectPlayers(startSlot, count, m, out)
        for i = 1, count do
            local orig = eligible[startSlot + i - 1]
            if orig then
                local pos    = orig.position
                local pi     = pickIdx(pos, m)
                local chosen = pi and byPos[pos][pi] or orig
                out[#out + 1] = chosen
                removeAt(pos, pi)
            end
        end
    end

    local starting11, bench = {}, {}
    selectPlayers(1,  11, mode,     starting11)
    selectPlayers(12, 7,  "strong", bench)

    -- ── Player-career rotation override ─────────────────────────────────
    -- When the AI manager rotates to a weaker XI (mode == "weak"), the
    -- user's own player can easily be left out purely because their rating
    -- isn't among the strongest available — but rotation games are exactly
    -- when a fringe squad player gets his chance. So 95% of the time, force
    -- them into the starting XI if the normal draw didn't already pick them.
    -- This NEVER overrides suspension/injury — an unavailable player still
    -- can't play no matter what (userPlayer simply won't be found below,
    -- since `eligible` excludes them).
    if mode == "weak" and teamID == self:getPlayerTeamID() then
        local userID = self:getPlayerID()
        if userID then
            local alreadyStarting = false
            for _, p in ipairs(starting11) do
                if p.CARD_ID == userID then alreadyStarting = true; break end
            end
            if not alreadyStarting and math.random() <= 0.95 then
                local userPlayer = nil
                for _, p in ipairs(eligible) do
                    if p.CARD_ID == userID then userPlayer = p; break end
                end
                if userPlayer then
                    -- If the initial draw had already put them on the bench,
                    -- pull them out of there first (they're being promoted).
                    for i = #bench, 1, -1 do
                        if bench[i].CARD_ID == userID then table.remove(bench, i); break end
                    end

                    -- Bump the weakest starter in the SAME position group;
                    -- fall back to the weakest starter in a compatible slot
                    -- (never swap a GK for an outfield player or vice versa).
                    local userGroup = POS_GROUP[userPlayer.position] or 3
                    local outIdx, outRating = nil, math.huge
                    for i, p in ipairs(starting11) do
                        if (POS_GROUP[p.position] or 0) == userGroup and (p.rating or 0) < outRating then
                            outIdx, outRating = i, (p.rating or 0)
                        end
                    end
                    if not outIdx then
                        local userIsGK = userGroup == 1
                        for i, p in ipairs(starting11) do
                            local pIsGK = (POS_GROUP[p.position] or 0) == 1
                            if pIsGK == userIsGK and (p.rating or 0) < outRating then
                                outIdx, outRating = i, (p.rating or 0)
                            end
                        end
                    end

                    if outIdx then
                        local displaced = starting11[outIdx]
                        starting11[outIdx] = userPlayer

                        -- Give the displaced starter a bench seat instead of
                        -- dropping straight to the reserves. A full bench's
                        -- weakest player ends up 8th, the reserves' first
                        -- place (removing him lost him from the squad: he was
                        -- already out of the position lists).
                        bench[#bench + 1] = displaced
                        table.sort(bench, function(a, b) return (a.rating or 0) > (b.rating or 0) end)
                    end
                end
            end
        end
    end

    -- Manager trust (PrismPro): how much the manager trusts the user's player
    -- decides whether he starts, sits on the bench, or stays out, within his
    -- own line (never a keeper for an outfield player). Fit players only.
    if teamID == self:getPlayerTeamID() then
        local PRO = rawget(_G, "PrismPro")
        if PRO and PRO.adjustXI then pcall(PRO.adjustXI, starting11, bench, eligible, mode) end
    end

    -- Top up the bench with the best available suspended/injured players
    -- ONLY if the fit squad wasn't deep enough to fill a normal bench —
    -- they still can never be in the starting XI.
    if #bench < 7 and #unavailable > 0 then
        local usedIDs = {}
        for _, p in ipairs(starting11) do usedIDs[p.CARD_ID] = true end
        for _, p in ipairs(bench)      do usedIDs[p.CARD_ID] = true end
        for _, p in ipairs(unavailable) do
            if #bench >= 7 then break end
            if not usedIDs[p.CARD_ID] then
                bench[#bench + 1] = p
                usedIDs[p.CARD_ID] = true
            end
        end
    end

    -- Rebuild the squad array: starters (1-11), bench (12-18), reserves (19+)
    local finalSquad, idx = {}, 1
    local starterIDs = {}
    local placedIDs  = {}
    for _, p in ipairs(starting11) do
        finalSquad[idx] = p.CARD_ID
        starterIDs[#starterIDs + 1] = p.CARD_ID
        placedIDs[p.CARD_ID] = true
        idx = idx + 1
    end
    for _, p in ipairs(bench) do
        finalSquad[idx] = p.CARD_ID
        placedIDs[p.CARD_ID] = true
        idx = idx + 1
    end
    -- Remaining eligible players first, then remaining unavailable players.
    for _, pos in ipairs(posOrder) do
        local list = byPos[pos]
        for i = 1, posCounts[pos] do
            local p = list[i]
            if not placedIDs[p.CARD_ID] then
                finalSquad[idx] = p.CARD_ID
                placedIDs[p.CARD_ID] = true
                idx = idx + 1
            end
        end
    end
    for _, p in ipairs(unavailable) do
        if not placedIDs[p.CARD_ID] then
            finalSquad[idx] = p.CARD_ID
            placedIDs[p.CARD_ID] = true
            idx = idx + 1
        end
    end

    -- Write back to cache (so getCachedTeamPlayers returns the new order)
    local TeamCachedData = sessionVars.get("TeamCachedData") or {}
    local reorderedPlayers = {}
    -- Build a lookup of CARD_ID -> player object
    local byID = {}
    for _, p in ipairs(players) do byID[p.CARD_ID] = p end
    for i, cid in ipairs(finalSquad) do
        reorderedPlayers[i] = byID[cid]
    end
    if TeamCachedData[teamID] then
        TeamCachedData[teamID].players = reorderedPlayers
    else
        TeamCachedData[teamID] = { players = reorderedPlayers, league = 1 }
    end
    sessionVars.set("TeamCachedData", TeamCachedData)

    -- Also write to the squad service so the FIFA match engine sees the XI
    -- when the user actually plays the match.
    if self.services and self.services.SquadManagementService then
        local ok = pcall(function()
            self.services.SquadManagementService.SetCurrentPlayerLineup(
                0, teamID, 0, 0, finalSquad)
        end)
        if not ok then
            -- Silently continue — the cache write above is the authoritative
            -- one for the Lua side; the service call is only for the match
            -- engine and failing it must not abort the matchday loop.
        end
    end

    sessionVars.set("PlayerCareerSquadPickKey", thisKey)

    return starterIDs
end

-- ── "Can the user play today?" gate ─────────────────────────────────────────
-- Returns true only if the user's controlled player is in the first 11 of
-- the cached squad for the user's team. Call this AFTER pickAISquad has run
-- (so the cache reflects the AI manager's current selection).
function PlayerCareer:canPlayMatch()
    if not isActive() then return true end   -- manager/tournament always plays
    local playerID = self:getPlayerID()
    if not playerID then return true end     -- no player chosen yet (shouldn't happen post-boot)

    local teamID = self:getPlayerTeamID()
    if not teamID then return false end

    local squad = getCachedTeamPlayers(teamID) or {}
    for i = 1, math.min(11, #squad) do
        if squad[i] and squad[i].CARD_ID == playerID then
            return true
        end
    end
    return false
end

-- Convenience for the UI: returns the user's player's starter index (1-11)
-- or 0 if benched, or -1 if not in the squad at all.
function PlayerCareer:getPlayerSquadStatus()
    if not isActive() then return -1 end
    local playerID = self:getPlayerID()
    if not playerID then return -1 end
    local teamID = self:getPlayerTeamID()
    if not teamID then return -1 end
    local squad = getCachedTeamPlayers(teamID) or {}
    for i = 1, #squad do
        if squad[i] and squad[i].CARD_ID == playerID then
            return (i <= 11) and i or 0
        end
    end
    return -1
end

-- ── Transfer-offer scan ─────────────────────────────────────────────────────
-- AITransfers.lua already writes offers for the user's team's players into
-- sessionVars.transferOffers (keyed by player CARD_ID). For manager career,
-- the user goes to the Transfer Hub to accept/reject each one. For player
-- career, we only surface offers for THE USER'S player — offers for teammates
-- are auto-resolved by AITransfers (see the hook we add in batchTransfers).
--
-- Returns the offer table for the user's player, or nil.
-- Offer shape (from AITransfers.lua):
--   { offeringClub = teamID, priceTag = fee, isLoan = bool, loanDuration = N }
function PlayerCareer:getOfferForMyPlayer()
    if not isActive() then return nil end
    local playerID = self:getPlayerID()
    if not playerID then return nil end
    local transferOffers = sessionVars.get("transferOffers") or {}
    return transferOffers[playerID]
end

-- User accepts the offer for their player. Calls the global transferPlayer()
-- (defined in TeamSelect.lua) which moves the player to the buying club,
-- records the transfer in transferHistory, and updates TeamCachedData.
-- After the transfer, currentSelectedTeamID is updated to the buying club
-- so the rest of the framework (matchday, standings, fixtures) follows the
-- player to their new club.
function PlayerCareer:acceptOffer()
    if not isActive() then return false end
    local playerID = self:getPlayerID()
    if not playerID then return false end
    local offer = self:getOfferForMyPlayer()
    if not offer then return false end

    local oldTeam = self:getPlayerTeamID()
    local newTeam = offer.offeringClub
    if not newTeam or newTeam == oldTeam then return false end

    -- Execute the transfer via the existing global.
    -- transferPlayer(playerID, sourceTeamID, targetTeamID, isLoan, loanDuration, isIntl)
    transferPlayer(playerID, oldTeam, newTeam, offer.isLoan == true, offer.loanDuration, false, offer.priceTag)

    -- Update currentSelectedTeamID so the framework follows the player.
    -- This is the key "player career" pivot: the user's identity moves with
    -- their player, not with a fixed club.
    currentSelectedTeamID = newTeam
    sessionVars.set("currentSelectedTeamID", newTeam)

    -- Resolve the league the new club plays in so fixtures / standings
    -- continue to resolve correctly. getTeamLeague is the existing global
    -- from TeamSelect.lua.
    local newLeague = getTeamLeague(newTeam)
    sessionVars.set("currentUserLeagueID", newLeague)

    -- Clear the offer
    local transferOffers = sessionVars.get("transferOffers") or {}
    transferOffers[playerID] = nil
    sessionVars.set("transferOffers", transferOffers)

    return true, newTeam
end

-- User rejects the offer. Simply clears the offer entry; AITransfers will not
-- re-create it for the same player in the same window (transferredPlayers is
-- not set, so the AI may try again next batch — this is intentional, matches
-- manager career behaviour where rejecting an offer doesn't prevent new ones).
function PlayerCareer:rejectOffer()
    if not isActive() then return false end
    local playerID = self:getPlayerID()
    if not playerID then return false end
    local transferOffers = sessionVars.get("transferOffers") or {}
    if not transferOffers[playerID] then return false end
    transferOffers[playerID] = nil
    sessionVars.set("transferOffers", transferOffers)
    return true
end

-- ── Teammate offer auto-resolution ──────────────────────────────────────────
-- Called from AITransfers:batchTransfers (via the hook we add). When the AI
-- generates an offer for a player on the user's team who is NOT the user's
-- controlled player, the AI manager auto-resolves it: accept if the fee
-- exceeds the player's computed value by 10%+, otherwise reject.
--
-- This runs INSIDE batchTransfers' existing pcall, so any error here is
-- swallowed by the existing error handling and never aborts the transfer
-- loop. We still pcall internally for belt-and-braces safety.
function PlayerCareer:autoResolveTeammateOffer(playerID, offer)
    if not isActive() then return nil end
    if not playerID or not offer then return nil end
    -- Don't auto-resolve the user's player's offer
    if playerID == self:getPlayerID() then return nil end

    local ok, result = pcall(function()
        local oldTeam = self:getPlayerTeamID()
        local newTeam = offer.offeringClub
        if not newTeam or newTeam == oldTeam then
            return "rejected"
        end

        -- Compute the player's transfer value using the existing globals
        -- (getPlayerInfo, computeTransferValue, playerReplacementCount,
        -- GetPlayerAge are all defined in PlayerAge.lua / Cores/).
        local squad = getCachedTeamPlayers(oldTeam) or {}
        local pInfo = getPlayerInfo(playerID, oldTeam, squad)
        local playerRating   = pInfo and pInfo.rating   or 50
        local playerPosition = pInfo and pInfo.position or "CM"
        local playerIndex    = pInfo and pInfo.index    or 0
        local repCount       = playerReplacementCount(oldTeam, playerPosition, squad) or 0
        local days           = daysLeftInTransferWindow(GLOBAL_DATE_PLACEHOLDER) or 30
        local playerValue, _ = computeTransferValue(
            GetPlayerAge(playerID) or 25,
            playerRating, playerPosition, playerIndex, repCount, days
        )

        -- Accept if the fee beats the value by 10%+ AND the selling team
        -- would still have enough players (squad size guard).
        local fee = offer.priceTag or 0
        local squadSize = #squad
        if fee >= playerValue * 1.10 and squadSize > 24 then
            -- Check budget
            local destBudget = GLOBAL_FUNDS and GLOBAL_FUNDS[newTeam] or 0
            if (not offer.isLoan) and destBudget < fee then
                return "rejected"
            end
            -- Execute
            transferPlayer(playerID, oldTeam, newTeam,
                           offer.isLoan == true, offer.loanDuration, false, fee)
            if not offer.isLoan and GLOBAL_FUNDS then
                GLOBAL_FUNDS[newTeam] = destBudget - fee
                GLOBAL_FUNDS[oldTeam] = (GLOBAL_FUNDS[oldTeam] or 0) + playerValue
            end
            return "accepted"
        end
        return "rejected"
    end)

    return ok and result or "error"
end

return PlayerCareer
