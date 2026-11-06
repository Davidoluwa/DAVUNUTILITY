local LoadSave = {}
local sessionVars, CareerModeLeagues, SquadState = nil, nil, nil

function LoadSave:new(init)
    local o = init or {}
    setmetatable(o, self)
    self.__index = self
    sessionVars       = init.sessionVars
    CareerModeLeagues = init.CareerModeLeagues
    SquadState        = init.SquadState
    o.services        = init.services
    return o
end

local function normalizeNumericKeys(tbl)
    if type(tbl) ~= "table" then return tbl end
    local normalized = {}
    for key, value in pairs(tbl) do
        local newKey = tonumber(key) or key
        normalized[newKey] = (type(value) == "table") and normalizeNumericKeys(value) or value
    end
    return normalized
end

local DAY = 86400
local function fromSeasonDOY(doy, seasonStartYear)
    if type(doy) ~= "number" then return nil end
    local year = tonumber(seasonStartYear)
    if not year then return nil end
    local aug1 = os.time({year=year, month=8, day=1, hour=12})
    local t    = os.date("*t", aug1 + (doy - 1) * DAY)
    return string.format("%02d%02d%02d", t.month, t.day, t.year % 100)
end

-- Dynamically determine the correct league ID for the user's team
local function getUserLeagueIDFromMatches(matches, teamID, saveMode)
    if not matches or not teamID then return nil end
    local targetType = (saveMode == "tourney") and "Competition" or "League"
    for _, match in ipairs(matches) do
        if (match.homeID == teamID or match.awayID == teamID) and match.matchType == targetType then
            return match.leagueID
        end
    end
    return nil
end

function LoadSave:loadSavedGame()
    -- Normalise save table
    if Save and type(Save) == "table" then
        Save = normalizeNumericKeys(Save)
    end
    
    --key to notify that game is replaying loaded data to memory
    sessionVars.set("_isReplaying", true)

    -- Basic session vars (excluding currentUserLeagueID – will set later)
    sessionVars.set("currentSelectedTeamID", Save.currentSelectedTeamID or currentSelectedTeamID)
    currentSelectedTeamID = sessionVars.get("currentSelectedTeamID")

    GLOBAL_DATE_PLACEHOLDER = Save.GLOBAL_DATE_PLACEHOLDER or GLOBAL_DATE_PLACEHOLDER or "01/07/25"
    sessionVars.set("GLOBAL_DATE_PLACEHOLDER", GLOBAL_DATE_PLACEHOLDER)
    local savedYY = tonumber((GLOBAL_DATE_PLACEHOLDER or "01/07/25"):sub(-2)) or 25
    CAREER_FULL_YEAR = tonumber(Save.careerFullYear) or tonumber((sessionVars.get("_careerFullYear"))) or (2000 + savedYY)
    sessionVars.set("_careerFullYear", CAREER_FULL_YEAR)
    sessionVars.set("_worldCupYear", Save.worldCupYear or nil)
    sessionVars.set("PlayerGoals",             Save.playerGoals              or {})
    sessionVars.set("PlayerAssists",           Save.playerAssists            or {})
    sessionVars.set("LeagueTeams",             Save.LeagueTeams              or {})
    sessionVars.set("Champion",                Save.Champion                 or nil)
    sessionVars.set("PreSeasonChampion",       Save.PreSeasonChampion        or nil)
    sessionVars.set("deadlineTime",            Save.deadlineTime             or nil)
    sessionVars.set("sheetData",               Save.sheetData                or nil)
    sessionVars.set("sheetIdx",                Save.sheetIdx                 or nil)
    sessionVars.set("redMatchCount",           Save.redMatchCount            or {})
    sessionVars.set("loanListed",              Save.loanListed               or {})
    sessionVars.set("notListed",               Save.notListed                or {})
    sessionVars.set("transferListed",          Save.transferListed           or {})
    sessionVars.set("transferOffers",          Save.transferOffers           or {})
    sessionVars.set("shortlistedPlayers",      Save.shortlistedPlayers       or {})
    sessionVars.set("scoutedPlayers",          Save.scoutedPlayers           or {})
    if Save.scoutParam then sessionVars.set("scoutParam", Save.scoutParam) end
    if Save.teamLoansIn then sessionVars.set("teamLoansIn", Save.teamLoansIn) end
    sessionVars.set("playerAppearances",       Save.playerApps               or {})
    sessionVars.set("GLOBAL_FUNDS",            Save.GLOBAL_FUNDS             or GLOBAL_FUNDS)
    CAREER_PLAYER_OVERRIDES = normalizeNumericKeys(Save.playerOverrides or {})
    sessionVars.set("PlayerDevInit", { mode = "load", data = Save.playerDev })   -- the hub takes over the development state
    sessionVars.set("_prismYouth", { raw = Save.youth or false })   -- PrismYouth decodes it on first use
    -- Player Career: the user's own player (a save from before PrismPro has only his id)
    sessionVars.set("_prismPro", nil)
    if Save.mode == "player" then
        local PRO = rawget(_G, "PrismPro")
        local restored = PRO and PRO.restore and select(2, pcall(PRO.restore, sessionVars, Save.pro))
        if restored ~= true then sessionVars.set("PlayerCareerPlayerID", tonumber(Save.playerCareerID)) end
    end

    local savedTransferCount = Save.transferCount or 0
    sessionVars.set("transferCount", savedTransferCount)
    -- no offers, alerts or window counters outside a window
    do local PW = rawget(_G, "PrismWindow"); if PW and PW.isOpen and not PW.isOpen(GLOBAL_DATE_PLACEHOLDER) then pcall(PW.close, sessionVars) end end
    -- a save without the setup gets the defaults
    sessionVars.set("_prismSetup", type(Save.setup) == "table" and Save.setup or nil)

    -- isSuspended normalisation
    local rawSusp, normSusp = Save.isSuspended or {}, {}
    for lgKey, players in pairs(rawSusp) do
        local lgNum = tonumber(lgKey)
        -- Entries that are not tables (a flat isSuspended[player] = 2) are skipped.
        if lgNum and type(players) == "table" then
            normSusp[lgNum] = {}
            for pKey, val in pairs(players) do
                local pNum = tonumber(pKey)
                if pNum then normSusp[lgNum][pNum] = val end
            end
        end
    end
    sessionVars.set("isSuspended", normSusp)
    isSuspended = normSusp
    -- Bans a save cannot count down are put right (a ban with no count serves one more match, a count with no
    -- ban is a ban, a count that is not a number is dropped with its ban); no card of an earlier career is
    -- carried into this one.
    do
        local susp, cnt = sessionVars.get("isSuspended"), sessionVars.get("redMatchCount")
        if type(cnt) ~= "table" then cnt = {}; sessionVars.set("redMatchCount", cnt) end
        sessionVars.set("matchdayRedCard", {})
        -- The day each injured player is fit again (a save without it: every injury is dated when first seen).
        do
            local un = {}
            if type(Save) == "table" and type(Save.injuryUntil) == "table" then for pid, u in pairs(Save.injuryUntil) do if type(pid) == "number" and type(u) == "number" then un[pid] = u end end end
            sessionVars.set("injuryUntil", un)
        end
        local Sx = rawget(_G, "PRISM_SUSP"); if Sx then Sx.pending = {}; Sx.pendingY = {}; Sx.cur = nil end
        -- The yellows of this season, per competition and player (number keys again).
        do
            local yc = {}
            if type(Save) == "table" and type(Save.yellowCount) == "table" then
                for c, t in pairs(Save.yellowCount) do
                    local cn = tonumber(c)
                    if cn and type(t) == "table" then
                        yc[cn] = {}
                        for pid, n in pairs(t) do local pn = tonumber(pid); if pn and type(n) == "number" then yc[cn][pn] = n end end
                    end
                end
            end
            sessionVars.set("yellowCount", yc)
        end
        for comp, bans in pairs(cnt) do
            if type(bans) ~= "table" then cnt[comp] = nil
            else
                for pid, n in pairs(bans) do
                    if type(n) ~= "number" or n ~= n or n < 1 then
                        bans[pid] = nil
                        local t = susp[comp]; if type(t) == "table" and t[pid] == 1 then t[pid] = nil end
                    else
                        local t = susp[comp]; if type(t) ~= "table" then t = {}; susp[comp] = t end
                        if t[pid] ~= 2 then t[pid] = 1 end
                    end
                end
            end
        end
        for comp, t in pairs(susp) do
            if type(t) == "table" then
                for pid, v in pairs(t) do
                    local bans = cnt[comp]
                    if v == 1 and not (type(bans) == "table" and bans[pid]) then
                        if type(bans) ~= "table" then bans = {}; cnt[comp] = bans end
                        bans[pid] = 1
                    end
                end
            end
        end
    end

    -- ── Match data loading (decompress and store) ─────────────────────────
    local leagueMatchData = {}
    local matchData       = {}
    local matchIdx        = 0
    local seasonYear = Save.seasonCalendar and tonumber(Save.seasonCalendar.year)

    if Save.matchData then
        for k, v in pairs(Save.matchData) do
            local lgID = tonumber(k) or k
            local isCompressed = v[1] and v[1].h ~= nil
            local expanded = {}
            for i = 1, #v do
                local m = v[i]
                if isCompressed then
                    expanded[i] = {
                        homeID    = m.h,
                        awayID    = m.a,
                        date      = (seasonYear and type(m.d) == "number") and fromSeasonDOY(m.d, seasonYear) or m.d,
                        matchType = m.mt,
                        matchday  = m.md,
                        leagueID  = lgID,
                    }
                else
                    if m.leagueID == nil then m.leagueID = lgID end
                    expanded[i] = m
                end
            end
            leagueMatchData[lgID] = expanded
            for i = 1, #expanded do
                matchIdx = matchIdx + 1
                matchData[matchIdx] = expanded[i]
            end
        end
    end

    sessionVars.set("MatchData",       matchData)
    sessionVars.set("LeagueMatchData", leagueMatchData)
    sessionVars.set("UCLLeagueID", leagueMatchData[2236] and 2236 or nil)

    -- ── Dynamic league ID for user ───────────────────────────────────────
    local computedLeagueID = getUserLeagueIDFromMatches(matchData, currentSelectedTeamID, Save.mode)
    local finalLeagueID = computedLeagueID or Save.currentLeagueID or getTeamLeague(currentSelectedTeamID)
    sessionVars.set("currentUserLeagueID", finalLeagueID)

    -- ── Authoritative squad restore ─────────────────────────────────
    -- New saves store playerRoster[playerID] = currentTeamID.  This is
    -- idempotent and survives multi-hop/circular transfers. Legacy saves are
    -- migrated by folding their old transfer log to the final destination.
    local roster, foldedLoans = Save.playerRoster, nil
    if not roster or next(roster) == nil then
        roster, foldedLoans = SquadState.fold(Save.transferHistory)
    end

    -- The youths go into their clubs first, so that their moves replay like any other player's.
    do local Y = rawget(_G, "PrismYouth"); if Y and Y.injectAll then pcall(Y.injectAll, sessionVars) end end
    SquadState.setRoster(roster)
    SquadState.restore(roster)
    -- restore() only sees the squads cacheAllTeamPlayers() cached (the career's leagues); a player bought
    -- from a classic, Rest-of-World or national side or from a league outside the career is in none of them.
    -- Open those clubs now; the roster moves him on.
    if SquadState.setOrigins and SquadState.placeStranded then
        SquadState.setOrigins(Save.playerOrigin, Save.transferHistory)
        pcall(SquadState.placeStranded, roster)
    end
    sessionVars.set("loanedPlayers", Save.loanedPlayers or foldedLoans or {})
    if type(prismLoanNormalize) == "function" then pcall(prismLoanNormalize) end   -- R98b: the save has the ids as strings

    local origin       = SquadState.originIndex()
    local notFirstTime = {}
    for playerID in pairs(roster) do
        notFirstTime[playerID] = origin[playerID]
    end
    sessionVars.set("notFirstTime", notFirstTime)

    -- Preserve the transfer-window lock exactly across reload. Old saves fall
    -- back to the same history/count rule used by the previous loader.
    if Save.transferLock then
        transferredPlayers = SquadState.unpackLock(Save.transferLock)
    elseif Save.transferHistory then
        local hist = Save.transferHistory
        local skip = #hist - savedTransferCount
        if skip < 0 then skip = 0 end
        transferredPlayers = {}
        for i = skip + 1, #hist do
            local rec = hist[i]
            if rec and rec.Player then transferredPlayers[rec.Player] = true end
        end
    else
        transferredPlayers = {}
    end

    if type(prismLoanLock) == "function" then pcall(prismLoanLock) end   -- R98d: the players on loan stay locked (an older save had no lock for them)

    -- Retain the full display/news history, but never replay it when restoring.
    transferHistory = Save.transferHistory or {}

    -- the transfer history screen's log (a save without one starts an empty log)
    do
        local H = rawget(_G, "PrismHistory")
        local ok, log = false, nil
        if H and H.restore then ok, log = pcall(H.restore, Save.transferLog) end
        sessionVars.set("transferLog", (ok and log) or (type(Save.transferLog) == "table" and Save.transferLog) or {})
    end

    -- ── Squad / formation ────────────────────────────────────────────────
    if sessionVars.get("sheetData") then
        local idx2  = sessionVars.get("sheetIdx") or 1
        local sheet = sessionVars.get("sheetData")[idx2]
        if sheet then Save.currentPlayersID = sheet.players end
    end

    if Save.currentPlayersID and #Save.currentPlayersID > 11 then
        local squadPlayers   = Save.currentPlayersID
        local TeamCachedData = sessionVars.get("TeamCachedData") or {}

        -- A saved sheet can predate transfers made after the last squad-screen
        -- visit. Reconcile it against the authoritative roster before writing
        -- it back, otherwise it can undo signings/sales that restore() applied.
        local reconciled, seen = {}, {}
        for i = 1, #squadPlayers do
            local pid = squadPlayers[i]
            -- the roster decides (nil: never moved; FREE_AGENT: released)
            local rk  = SquadState.roster()[pid]
            local at
            if rk ~= nil then at = (rk ~= SquadState.FREE_AGENT) and rk or false
            else local Y = rawget(_G, "PrismYouth"); at = Y and Y.clubOf and Y.clubOf(pid) or nil end
            if not seen[pid] and (at == nil or at == currentSelectedTeamID) then
                reconciled[#reconciled + 1] = pid
                seen[pid] = true
            end
        end
        for playerID, teamID in pairs(roster) do
            if teamID == currentSelectedTeamID and not seen[playerID] then
                reconciled[#reconciled + 1] = playerID
                seen[playerID] = true
            end
        end
        squadPlayers = reconciled

        -- Fetch the club first: a deferred club fetched after this write would take the saved XI as its baseline.
        if not TeamCachedData[currentSelectedTeamID] then pcall(getCachedTeamPlayers, currentSelectedTeamID); TeamCachedData = sessionVars.get("TeamCachedData") or TeamCachedData end
        self.services.SquadManagementService.SetCurrentPlayerLineup(0, currentSelectedTeamID, 0, 0, squadPlayers)
        local players = self.services.SquadManagementService.GetCurrentPlayerLineup(0, currentSelectedTeamID, 0)
        if not TeamCachedData[currentSelectedTeamID] then
            local cachedPlayers = getCachedTeamPlayers(currentSelectedTeamID) or {}
            TeamCachedData[currentSelectedTeamID] = {
                players = cachedPlayers,
                league = finalLeagueID
            }
        end
        TeamCachedData[currentSelectedTeamID].players = players
        sessionVars.set("TeamCachedData", TeamCachedData)
        sessionVars.set("currentPlayersID", squadPlayers)
    end

    if Save.seasonCalendar then
	    sessionVars.set("_calendar_data", Save.seasonCalendar)
	end

    if Save.currentFormationID then
        self.services.TacticsService.SetFormation(0, currentSelectedTeamID, Save.currentFormationID)
        sessionVars.set("currentFormationID", Save.currentFormationID)
    end

    Save = nil
    sessionVars.set("_isReplaying", nil)
end

return LoadSave
