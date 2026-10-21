-- Singleton Module for compact JSON serialising
-- Depends on: Save (accumulator), bgProcessor (BackgroundProcessor)
--
-- Flow:
--   1. saveProgress() pauses the BP timer and calls startSave(callback).
--   2. MatchSelect startSave fires the callback immediately (no popup).
--   3. The callback resumes the BP timer, assembles the save table, hands it
--      to Save:saveProgress(), then calls flushAndStream().
--   4. flushAndStream() chains each chunk delivery via bgProcessor:runTask()
--      with STREAM_INTERVAL between sends. _sT is injected first to clear the
--      receiver. Save streaming is intentionally silent.

local Save = ...

local Serializer   = {}
local sessionVars  = nil
local Date         = nil
local bgProcessor  = nil
local SquadState   = nil
local saveComplete = nil
local updateSave, startSave = nil, nil
local nav = nil
local isStreaming = false

-- Base streaming config
local DEFAULT_STREAM_INTERVAL = 0.02
local STREAM_INTERVAL         = DEFAULT_STREAM_INTERVAL

local SAVE_COMPLETE_DELAY = 0.1
local MAX_RETRIES         = 4

-- ── Construction ──────────────────────────────────────────────────────────────

function Serializer:new(init, obj)
    local o = obj or (init or {})
    setmetatable(o, self)
    self.__index = self

    o.nav        = init.nav
    nav          = init.nav
    sessionVars  = init.sessionVars
    Date         = init.Date
    bgProcessor  = init.bgProcessor
    SquadState   = init.SquadState
    updateSave   = init.updateSave
    startSave    = init.startSave

    return o
end

local currentSaveData = nil

local function toPercent(part, total)
    if total == 0 then return 0 end
    local percent = (part / total) * 100
    percent = math.floor(percent * 100 + 0.5) / 100
    return percent
end

local function stringifyKeys(t)
    if type(t) ~= "table" then return t end
    local res = {}
    for k, v in pairs(t) do
        local newKey = type(k) == "number" and tostring(k) or k
        res[newKey] = (type(v) == "table") and stringifyKeys(v) or v
    end
    return res
end

-- ── Internal: stream chunks ───────────────────────────────────────────────────

function flushAndStream()
    local chunks = Save:flushChunks()
    local total  = #chunks

    Save:sendChunk("_sT")
    Save:sendChunk("{")

    if total == 0 then
        isStreaming = false
        return
    end

    local function sendNext(i)
        if i > total then
            isStreaming = false
            return
        end

        Save:sendChunk(chunks[i])

        bgProcessor:runTask(function()
            sendNext(i + 1)
        end, STREAM_INTERVAL)
    end

    bgProcessor:runTask(function()
        sendNext(1)
    end, STREAM_INTERVAL)
end

-- ── Public: saveProgress ──────────────────────────────────────────────────────

function Serializer:saveProgress()
    if isStreaming then
        return
    end
    isStreaming = true

    -- Pause while entering the save path, then resume immediately inside the
    -- direct startSave callback so the chunk scheduler can use runTask().
    bgProcessor:pause()

    startSave(function()
        -- a save that raises must not leave isStreaming set
        local prismOk, prismErr = pcall(function()
        bgProcessor:start()

        -- this mode's career globals, put back by TeamSelect when its career loads again
        sessionVars.set("_prismGlobals", { th = transferHistory, tp = transferredPlayers, ovr = CAREER_PLAYER_OVERRIDES })
        -- A save is made on the hub: whatever is still pending belongs to a match left unrecorded.
        do local S = rawget(_G, "PRISM_SUSP"); if S and S.discardPending then pcall(S.discardPending) end end
        -- Every injury has the day he is fit again before it is saved.
        do local S = rawget(_G, "PRISM_SUSP"); if S and S.syncInjuries then pcall(S.syncInjuries) end end
        local leagueMatchData = sessionVars.get("LeagueMatchData")
        local sheetData       = sessionVars.get("sheetData")
        local transferOffers  = sessionVars.get("transferOffers") or {}
        local transferListed  = sessionVars.get("transferListed") or {}
        local loanListed      = sessionVars.get("loanListed") or {}
        local notListed       = sessionVars.get("notListed") or {}

        -- Persist the answer (player -> current club), not a relative transfer
        -- replay path. Circular moves compact away automatically.
        -- the hub builds this Serializer without SquadState in scope
        local SquadState = SquadState or rawget(_G, "PRISM_SQUAD_STATE")
        local playerRoster = (SquadState and SquadState.compact())
            or sessionVars.get("playerRoster") or {}
        local transferLock = (SquadState and SquadState.packLock(transferredPlayers)) or {}

        local save = {
            transferCount           = sessionVars.get("transferCount") or 0,
            matchData               = leagueMatchData or {},
            playerGoals             = sessionVars.get("PlayerGoals"),
            playerAssists           = sessionVars.get("PlayerAssists") or {},
            playerApps = sessionVars.get("playerAppearances") or {},
            currentSelectedTeamID   = currentSelectedTeamID,
            GLOBAL_DATE_PLACEHOLDER = tostring(GLOBAL_DATE_PLACEHOLDER),
            LeagueTeams             = sessionVars.get("LeagueTeams"),
            Champion               = sessionVars.get("Champion"),
            PreSeasonChampion      = sessionVars.get("PreSeasonChampion"),
            GLOBAL_FUNDS            = stringifyKeys(GLOBAL_FUNDS),
            playerRoster            = playerRoster,
            -- origins of the moved players (SquadState.packOrigins)
            playerOrigin            = (function() local SS = SquadState or rawget(_G, "PRISM_SQUAD_STATE"); if SS and SS.packOrigins then local ok, v = pcall(SS.packOrigins, playerRoster); return ok and v or nil end end)(),
            loanedPlayers           = sessionVars.get("loanedPlayers") or {},
            isSuspended             = stringifyKeys(sessionVars.get("isSuspended") or {}),
            redMatchCount           = stringifyKeys(sessionVars.get("redMatchCount") or {}),
            -- the day each injured player is fit again
            injuryUntil             = stringifyKeys(sessionVars.get("injuryUntil") or {}),
            -- the yellows each player has collected in each competition this season
            yellowCount             = stringifyKeys(sessionVars.get("yellowCount") or {}),
            careerFullYear          = tonumber(rawget(_G, "CAREER_FULL_YEAR")) or tonumber((sessionVars.get("_careerFullYear"))),
            worldCupYear            = sessionVars.get("_worldCupYear"),
            transferLock            = transferLock,
            -- Full uncapped log remains for news/history only; load does not
            -- replay it when playerRoster is present.
            -- The newest KEEP records and every active loan's; the session keeps the same log as the save.
            transferHistory         = (function()
                local h, KEEP = transferHistory, 3000
                if type(h) ~= "table" or #h <= KEEP then return h end
                local loans = sessionVars.get("loanedPlayers") or {}
                local out, first = {}, #h - KEEP + 1
                for i = 1, #h do
                    local r = h[i]
                    if i >= first or (type(r) == "table" and r.isLoan and (loans[r.Player] or loans[tostring(r.Player)])) then out[#out + 1] = r end
                end
                transferHistory = out
                return out
            end)(),
            playerOverrides         = stringifyKeys(
                rawget(_G, "CAREER_PLAYER_OVERRIDES") or {}),
            transferOffers          = transferOffers,
            transferListed          = transferListed,
            loanListed              = loanListed,
            notListed               = notListed,
            shortlistedPlayers      = stringifyKeys(sessionVars.get("shortlistedPlayers") or {}),
            scoutedPlayers          = stringifyKeys(sessionVars.get("scoutedPlayers") or {}),
            scoutParam              = stringifyKeys(sessionVars.get("scoutParam") or {}),
            teamLoansIn             = stringifyKeys(sessionVars.get("teamLoansIn") or {}),
            currentLeagueID         = sessionVars.get("InLeagueMode")
                                      and sessionVars.get("currentUserLeagueID")
                                      or getTeamLeague(currentSelectedTeamID),
            mode                    = sessionVars.get("InLeagueMode") and "league"
                                      or (sessionVars.get("InPlayerCareerMode") and "player")
                                      or (sessionVars.get("InCareerMode") and "manager" or "tourney"),
            -- Player Career: the user's own player (PrismPro: who he is, his build, his career)
            pro                     = (function() local PRO = rawget(_G, "PrismPro"); if PRO and PRO.serialize then local ok, v = pcall(PRO.serialize); return ok and v or nil end end)(),
            playerDev               = (function() local CD = rawget(_G, "CareerDev"); if CD and CD.serialize then local ok, v = pcall(CD.serialize); return ok and v or nil end end)(), -- player development state
            -- the transfer history
            transferLog             = (function() local H = rawget(_G, "PrismHistory"); if H and H.serialize then local ok, v = pcall(H.serialize, sessionVars); return ok and v or nil end end)(),
            setup                   = sessionVars.get("_prismSetup"),
            -- the youth system's state
            youth                   = (function() local Y = rawget(_G, "PrismYouth"); if Y and Y.serialize then local ok, v = pcall(Y.serialize); return ok and v or nil end end)(),
            saved                   = true,
        }

        -- sheetData branch
        if not sheetData then
            local currentPlayersID = sessionVars.get("currentPlayersID")
            if currentPlayersID then
                save.currentPlayersID = currentPlayersID
            end
        else
            save.sheetData = sheetData
            save.sheetIdx  = sessionVars.get("sheetIdx")
        end

        -- The squad in its live order (the live lineup) goes into currentPlayersID and the active sheet.
        do
            local cache = sessionVars.get("TeamCachedData")
            local entry = type(cache) == "table" and cache[currentSelectedTeamID] or nil
            local ps = type(entry) == "table" and entry.players or nil
            if type(ps) == "table" and #ps > 11 then
                -- The live squad is the truth. SquadState.clubOf is not consulted: a player the database
                -- also lists at a Rest of World side can have that side as his "origin".
                local live, seen = {}, {}
                for i = 1, #ps do
                    local p = ps[i]
                    local id = type(p) == "table" and tonumber(p.CARD_ID or p.playerID) or nil
                    if id and not seen[id] then live[#live + 1] = id; seen[id] = true end
                end
                if #live > 11 then
                    save.currentPlayersID = live
                    if type(save.sheetData) == "table" then
                        local idx = tonumber(save.sheetIdx) or 1
                        local sh = save.sheetData[idx]
                        if type(sh) == "table" then
                            local copy, s2 = {}, {}
                            for k, v in pairs(save.sheetData) do copy[k] = v end
                            for k, v in pairs(sh) do s2[k] = v end
                            s2.players = live
                            copy[idx] = s2
                            save.sheetData = copy
                        end
                    end
                end
            end
        end
        local cal = sessionVars.get("_calendar_data")
                if cal then
                    save.seasonCalendar = cal
                end

        -- Optional fields
        if sessionVars.get("currentFormationID") then
            save.currentFormationID = sessionVars.get("currentFormationID")
        end

        if Date:isDeadline() then
            save.deadlineTime = sessionVars.get("deadlineTime")
        end

        -- Player Career: the user's player id (PrismPro.serialize carries the rest)
        if sessionVars.get("InPlayerCareerMode") then
            save.playerCareerID = sessionVars.get("PlayerCareerPlayerID")
        end

        -- Store globally for retries
        currentSaveData = save

        -- Write the entire save in one call via FileBridge
        -- (no chunking, no HTTP, no control words)
        local wrote = Save:writeFile(save)
        if wrote == false and updateSave then   -- the player is told when a save failed
            pcall(updateSave, "Your career could not be saved. The storage may be full or not writable: free some space and save again.", {"Ok"}, nil)
        end

        -- Silent/direct save: there is no save overlay to dismiss.
        isStreaming = false
        end)
        if not prismOk then   -- the save raised: clear the flag, log the error, tell the player
            isStreaming = false
            local f = rawget(_G, "F16_SVC"); if f and f.Cmd then pcall(f.Cmd, "log:save: the save raised: " .. tostring(prismErr):gsub("%c", " "):sub(1, 300)) end
            if updateSave then pcall(updateSave, "Your career could not be saved (" .. tostring(prismErr):sub(1, 80) .. "). Try again.", {"Ok"}, nil) end
        end
    end)
end

return Serializer
