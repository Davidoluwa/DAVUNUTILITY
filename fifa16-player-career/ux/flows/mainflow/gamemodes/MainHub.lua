local eventmanager, UI, tabsData, sessionVars, BackgroundProcessor, FCPopup, Timer, TeamStats, UIManager, NativePlayerPreview = ...

local MainHub = {}
local EventTypes = eventmanager.FE.FIFA.EventTypes

local ACT_MATCH_PLAY     = "act_qm_home_play"
local ACT_QM_CANCEL      = "act_qm_cancel"
local DEFAULT_RECT_COLOR = "0x1A1A1A"
local QM_KIT_TYPES       = { 0, 1, 3 }
local QM_TEAM_TOGGLE     = 2
local QM_LEAGUE_TOGGLE   = 1
local QM_COUNTRY_TOGGLE  = 0
local SAVE_PATH          = "/Save/Save.lua"
local headlines = { "Career", "Quick Match", "Tournaments", "League" }   -- locked variant: no Volta; pt-BR: no Customize, Career first

-- Volta (5v5 street) tab. It reuses the Quick Match panel; PlayMatch arms the
-- match it launches with currentMatch.F16Volta, and ClassicMatch/PlayMatch/
-- Match.lua (setTeams, which every mode's match goes through) consumes that arm
-- and switches the paired APK's street mode on or off for that one match.
local VOLTA_TAB = tabsData.VOLTA_TAB or 6
local QM_TEXT = {
    quick = { home = "QUICK MATCH  •  ONE-OFF MATCH", setup = "QUICK MATCH  •  SELECT TEAMS  •  SELECT KITS",
              play = "PLAY QUICK MATCH" },
    volta = { home = "VOLTA  •  5V5 STREET FOOTBALL", setup = "VOLTA  •  SELECT TEAMS  •  SELECT KITS",
              play = "PLAY VOLTA" }
}

-- F16Service is the paired APK's front-end service (libcloth). Missing on an
-- APK without it: then every match simply stays a normal match.
local function setStreetMode(api, on)
    local ok, f16 = pcall(api, "F16Service")
    if not ok or not f16 or not f16.Set then return false end
    return pcall(f16.Set, on and "street=on" or "street=off")
end

-- Volta mutes commentary for its match (ClassicMatch/PlayMatch/Match.lua) and keeps the player's own volume in
-- f16SavedCommentaryVolume; back on the hub it is always given back. 2 = VOLUME_ID.COMMENTARY_VOLUME_ID.
local function restoreCommentary(api)
    if f16SavedCommentaryVolume == nil then return end
    local ok, settings = pcall(api, "SettingsService")
    if ok and settings and settings.SaveAudioOptionValue then
        pcall(settings.SaveAudioOptionValue, 2, f16SavedCommentaryVolume)
    end
    f16SavedCommentaryVolume = nil
end

local ClassicMatchList = {
    { HomeTeamID = 1, AwayTeamID = 10, data = {}, StadiumID1 = 156, StadiumID2 = 246 }
}

currentMatch = currentMatch or {}
currentMatch.HomeTeamID = currentMatch.HomeTeamID or 0
currentMatch.AwayTeamID = currentMatch.AwayTeamID or 0
currentMatch.Side = currentMatch.Side or 0
currentMatch.HomeKitIndex = currentMatch.HomeKitIndex or 0
currentMatch.AwayKitIndex = currentMatch.AwayKitIndex or 1
currentMatch.StadiumID1 = currentMatch.StadiumID1 or 0
currentMatch.StadiumID2 = currentMatch.StadiumID2 or 0

--- Puts /Save/Save.lua right with libpv's career store before the game reads it: restored from the newest
--- verified generation when it is missing, damaged or older; taken in as the newest when an older build wrote it.
--- Returns the store's answer ("ok:..." or "err:..."), or nil when there is no store (an APK without it).
-- path: the save being read; its file name is the store slot
local function prismRecoverSave(path)
    local f = rawget(_G, "F16_SVC")
    if not (f and f.Cmd and f.Out) then return nil end
    local slotFile = tostring(path or ""):match("([^/]+)$") or "Save.lua"
    local ok, r = pcall(function() f.Cmd("store:recover|" .. slotFile); return tostring(f.Out()) end)
    if not ok or not r or r:sub(1, 3) ~= "ok:" and r:sub(1, 4) ~= "err:" then return nil end   -- an APK without the store
    if r:sub(1, 10) ~= "ok:current" and r:sub(1, 8) ~= "ok:empty" then
        pcall(f.Cmd, "log:save: " .. r)
        if r:find("restored", 1, true) then rawset(_G, "PRISM_SAVE_KEEPALL", true) end
    end
    return r
end
local function readJSON(path, callback)
    if path == SAVE_PATH then
        -- the file to read: the career's slot, or the newest save
        do local PS = rawget(_G, "PrismSlots"); if PS and PS.readPath then local okP, p = pcall(PS.readPath); if okP and p then path = p end end end
        prismRecoverSave(path)
    end
    json.load(function(data, err)
        -- a save read whole tells the slot index what it lacks for that slot
        do local PS = rawget(_G, "PrismSlots"); if PS and PS.noteRead then pcall(PS.noteRead, path, data) end end
        callback(data)
    end, path)
end

-- Peek /Save/Save.lua without touching any live gameplay session state.
-- Same check the career mode framework already does before letting you
-- load (see PremierLeague/MatchSelect.lua's validateSave / checkSaveHealth)
-- so we stay consistent with what counts as "a real save" elsewhere.
--
-- IMPORTANT: also sets the GLOBAL `Save` table on success, exactly like
-- the original MainMenu/MenuCM/PlayHub.lua's validateSave did. LoadSave.lua
-- never receives the save data as a parameter — every single line in
-- LoadSave:loadSavedGame() reads a bare global `Save` (Save.mode,
-- Save.LeagueTeams, Save.matchData, ...). Skipping this line is exactly
-- why loading silently crashed: by the time TeamSelect.lua's loadmode
-- branch called loadSave:loadSavedGame(), the global Save was still nil,
-- so the very first Save.currentSelectedTeamID lookup indexed nil.
local function validateSave(callback)
    readJSON(SAVE_PATH, function(data)
        if data and data.saved then
            Save = data
            callback(true, data)
        else
            callback(false)
        end
    end)
end

local function safeTeamName(loc, teamID)
    if not (loc and teamID) then return "" end
    local ok, name = pcall(function()
        return loc.LocalizeString("TeamName_Abbr15_" .. teamID)
    end)
    return (ok and name) or ""
end

local function kitLabel(kitType)
    if kitType == 1 then return "AWAY KIT" end
    if kitType == 3 then return "THIRD KIT" end
    return "HOME KIT"
end

local function safeServiceCall(fn, ...)
    if not fn then return nil end
    local ok, value = pcall(fn, ...)
    if ok then return value end
    return nil
end

-- Mirrors Liga/Data/LoadSave.lua's normalizeNumericKeys exactly. JSON object
-- keys always come back as strings (e.g. LeagueTeams["13"], matchData["1000"]),
-- but every lookup in TeamStats.lua indexes by the numeric leagueID. Without
-- this, every single lookup silently misses its key and stats stay empty —
-- this is the actual cause of the empty stats panel.
local function normalizeNumericKeys(tbl)
    if type(tbl) ~= "table" then return tbl end
    local normalized = {}
    for key, value in pairs(tbl) do
        local newKey = tonumber(key) or key
        normalized[newKey] = (type(value) == "table") and normalizeNumericKeys(value) or value
    end
    return normalized
end

-- Mirrors Liga/Data/LoadSave.lua's getUserLeagueIDFromMatches exactly. A
-- tourney save's Save.currentLeagueID is NOT the competition the team's
-- matches are actually filed under (that's leagueID 1000 / World Cup
-- group stage) — the career framework never trusts currentLeagueID
-- blindly, it scans the matches for the team's real competition first.
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

-- Primes just enough sessionVars/global state for TeamStats to compute a
-- league position from the save — WITHOUT replaying the whole save
-- (transfers, squads, formations, suspensions, etc). That full replay is
-- LoadSave:loadSavedGame()'s job and only happens once the player
-- actually commits to loading from the Career/Tournament tab. Returns the
-- resolved leagueID so the caller can also drive the theme off it.
local function primeStatsContext(careerType, data)
    sessionVars.setContext(careerType)
    -- A live career owns its context: its tables are newer than the file, so the peek must not overwrite them.
    if sessionVars.get("CareerMode") then return sessionVars.get("currentUserLeagueID") or data.currentLeagueID end

    local leagueTeams  = normalizeNumericKeys(data.LeagueTeams or {})
    local rawMatchData = normalizeNumericKeys(data.matchData or {})

    local leagueMatchData = {}
    local flatMatches = {}
    for lgID, v in pairs(rawMatchData) do
        local isCompressed = v[1] and v[1].h ~= nil
        local expanded = {}
        for i = 1, #v do
            local m = v[i]
            if isCompressed then
                expanded[i] = {
                    homeID    = m.h,
                    awayID    = m.a,
                    date      = m.d,
                    matchType = m.mt,
                    matchday  = m.md,
                    leagueID  = lgID
                }
            else
                if m.leagueID == nil then m.leagueID = lgID end
                expanded[i] = m
            end
            flatMatches[#flatMatches + 1] = expanded[i]
        end
        leagueMatchData[lgID] = expanded
    end

    local computedLeagueID = getUserLeagueIDFromMatches(flatMatches, data.currentSelectedTeamID, careerType)
    local finalLeagueID = computedLeagueID or data.currentLeagueID

    sessionVars.set("LeagueTeams", leagueTeams)
    sessionVars.set("LeagueMatchData", leagueMatchData)
    sessionVars.set("currentUserLeagueID", finalLeagueID)
    currentSelectedTeamID = data.currentSelectedTeamID

    return finalLeagueID
end

function MainHub:new(init)
    local o = init or {}
    setmetatable(o, self)
    self.__index = self

    -- Back on the hub: nothing is armed as Volta, and the APK is in normal mode
    -- until a match is launched from the Volta tab.
    currentMatch.F16Volta = nil
    setStreetMode(o.api, false)
    restoreCommentary(o.api)
    -- locked variant: libcloth's extras off (cloth physics, 3D crowd, colour grade, depth of field, post finish,
    -- atmosphere, material shading), no street mode, no Player Lock
    do local okf, f16 = pcall(o.api, "F16Service"); if okf and f16 and f16.Set then
      for _, kv in ipairs({ "street=off", "player_lock=off", "cloth=off", "collision=off", "crowd=off", "grade=off", "dof=off", "post=off", "post_bloom=off", "post_grade=off", "post_haze=off", "post_aa=off", "atmosphere=off", "materials=off" }) do pcall(f16.Set, kv) end
    end end
    -- F16Service for every screen (NativePlayerData, ages, Prism); the career's development leaves the database.
    if rawget(_G, "F16_SVC") == nil then local okF, svcF = pcall(o.api, "F16Service"); if okF and svcF then rawset(_G, "F16_SVC", svcF) end end
    do local CD = rawget(_G, "CareerDev"); if CD and CD.revertAll then pcall(CD.revertAll) end end
    do local CS = rawget(_G, "CustomizeStore"); if CS and CS.boot then pcall(CS.boot) end end   -- the Customize editor's edits

    -- The menu is no mode's. A way back here that skipped the mode's own exit leaves its flag on, and the menu's tabs
    -- (Cores/UI.lua picks them by mode) would then be a career's, which the menu does not have.
    sessionVars.set("InCareerMode", false); sessionVars.set("InPlayerCareerMode", false)
    sessionVars.set("InTourneyMode", false); sessionVars.set("InLeagueMode", false)
    -- no career screen stays over the menu
    do local PS = rawget(_G, "PRISM_SKIN"); local M = PS and PS.module; if M and M.menuReset then pcall(M.menuReset) end end

    -- the career sets its own difficulty; the main menu goes back to the game's
    do local PSU = rawget(_G, "PrismSetup"); if PSU and PSU.restoreDifficulty then pcall(PSU.restoreDifficulty, o.api) end end
    o.team1 = { name = "$Crest", id = 1 }
    o.team2 = { name = "$Crest", id = 10 }
    o.menubg = { name = "$_BgMainMenu", id = 0 }
    o.currentTabInView = false

    -- Quick Match has two visual states on Tab 1. The home state remains
    -- visually unchanged in the layout; this flag only controls which group is visible.
    o.qmSetupOpen = false
    o.qmSnapshot = nil
    o.qmTeams = { [0] = {}, [1] = {} }
    o.qmSelector = { [0] = {}, [1] = {} }
    o.qmCountries = nil
    o.qmKitType = { [0] = currentMatch.HomeKitIndex or 0, [1] = currentMatch.AwayKitIndex or 1 }
    o.qmPreviewPlayers = { [0] = 0, [1] = 0 }
    o.services = {
        MatchSetup = o.api("MatchSetupService"),
        MatchInfo = o.api("MatchInfoService"),
        GameSetup = o.api("GameSetupService"),
        Country = o.api("CountryService"),
        Team = o.api("TeamService"),
        SquadMgt = o.api("SquadMgtService"),
        EventManagerService = o.api("EventManagerService")
    }

    -- V7.8 native renderer exposes five fully independent slots. Quick Match
    -- owns slots 0 and 1 while this screen is alive: home on the left, away
    -- on the right. They remain hidden until the inline setup state opens.
    o.qmPreview = {
        [0] = NativePlayerPreview:new(o.api, 0),
        [1] = NativePlayerPreview:new(o.api, 1)
    }

    -- Set by refreshSaveStatus() once a matching save is found; drives
    -- bnd_rectColor below the same way Career mode's UIManager does.
    o.themeLeagueID = nil
    o.nav.Back = function() o.nav.Event(nil, "evt_hide_overlay") validateSave(function(save, data) if save then sessionVars.setContext(data.mode) end end) end
    nav = o.nav
    math.randomseed(os.clock() * 1357 + os.time())
    local random2 = math.random(9)

    o.TeamStats = TeamStats:new({ loc = o.loc })

    o.im.Subscribe("bnd_menu_bg", function()
        o.menubg.id = random2
        o.im.Publish("bnd_menu_bg", o.menubg)
    end)
    
    o.im.Subscribe("headlines", function()
        o:toggleHeadline(0)
    end)

    o.im.Subscribe("bnd_team1", function()
        o.im.Publish("bnd_team1", o.team1)
    end)

    o.im.Subscribe("bnd_team2", function()
        o.im.Publish("bnd_team2", o.team2)
    end)


    local qmBindings = {
        "bnd_qm_default_visible", "bnd_qm_setup_visible",
        "bnd_qm_subtitle_home", "bnd_qm_subtitle_setup", "bnd_qm_play_label",
        "bnd_qm_home_crest", "bnd_qm_away_crest",
        "bnd_qm_home_country", "bnd_qm_away_country",
        "bnd_qm_home_leaguecrest", "bnd_qm_away_leaguecrest",
        "bnd_qm_home_leaguename", "bnd_qm_away_leaguename",
        "bnd_qm_home_teamname", "bnd_qm_away_teamname",
        "bnd_qm_home_star", "bnd_qm_away_star",
        "bnd_qm_home_kit", "bnd_qm_away_kit",
        "bnd_qm_home_kitlabel", "bnd_qm_away_kitlabel",
        "bnd_qm_home_kit0", "bnd_qm_home_kit1", "bnd_qm_home_kit3",
        "bnd_qm_away_kit0", "bnd_qm_away_kit1", "bnd_qm_away_kit3",
        "bnd_qm_home_kit0_selected", "bnd_qm_home_kit1_selected", "bnd_qm_home_kit3_selected",
        "bnd_qm_away_kit0_selected", "bnd_qm_away_kit1_selected", "bnd_qm_away_kit3_selected",
        "bnd_qm_home_kit0_dim", "bnd_qm_home_kit1_dim", "bnd_qm_home_kit3_dim",
        "bnd_qm_away_kit0_dim", "bnd_qm_away_kit1_dim", "bnd_qm_away_kit3_dim"
    }
    for _, binding in ipairs(qmBindings) do
        o.im.Subscribe(binding, function() o:publishQuickMatchSetup() end)
    end

    -- Theme: neutral fill until a save is found, then the same
    -- league-colour lookup Career mode drives via UIManager.lua.
    o.im.Subscribe("bnd_rectColor", function()
        if o.themeLeagueID then
            sessionVars.set("currentUserLeagueID", o.themeLeagueID)
            UIManager.setTheme(o.im, "0x303030")
        else
            o.im.Publish("bnd_rectColor", DEFAULT_RECT_COLOR)
        end
    end)

    o.FCPopup = FCPopup:new({ nav = o.nav })

    o.backgroundProcessor = BackgroundProcessor:new({
        im = o.im,
        Timer = Timer,
        idleTimeout = 0,
        maxFrameTime = 0
    })

    o.isBtnAnimating = false

    o.ui = UI:new({
        im = o.im,
        nav = o.nav,
        mainHub = o,
        tabsData = tabsData,
        TeamStats = o.TeamStats,
        backgroundProcessor = o.backgroundProcessor,
        animateTabButtons = function(tn, cfg, dir, atype, sx, cb)
            o:animateTabButtons(tn, cfg, dir, atype, sx, cb)
        end,
        swipeTabs = function(startX, targetX, cb)
            o:animateSwipeTabs(startX, targetX, cb)
        end
    })

    o.im.RegisterAction(ACT_MATCH_PLAY, function(actionName, data)
        o:PlayMatch()
    end)
    o.im.RegisterAction(ACT_QM_CANCEL, function() o:closeQuickMatchSetup() end)

    local teamToggleActions = {
        { "act_qm_home_team_prev", 0, QM_TEAM_TOGGLE, -1 },
        { "act_qm_home_team_next", 0, QM_TEAM_TOGGLE,  1 },
        { "act_qm_away_team_prev", 1, QM_TEAM_TOGGLE, -1 },
        { "act_qm_away_team_next", 1, QM_TEAM_TOGGLE,  1 },
        { "act_qm_home_league_prev", 0, QM_LEAGUE_TOGGLE, -1 },
        { "act_qm_home_league_next", 0, QM_LEAGUE_TOGGLE,  1 },
        { "act_qm_away_league_prev", 1, QM_LEAGUE_TOGGLE, -1 },
        { "act_qm_away_league_next", 1, QM_LEAGUE_TOGGLE,  1 },
        { "act_qm_home_country_prev", 0, QM_COUNTRY_TOGGLE, -1 },
        { "act_qm_home_country_next", 0, QM_COUNTRY_TOGGLE,  1 },
        { "act_qm_away_country_prev", 1, QM_COUNTRY_TOGGLE, -1 },
        { "act_qm_away_country_next", 1, QM_COUNTRY_TOGGLE,  1 }
    }
    for _, item in ipairs(teamToggleActions) do
        o.im.RegisterAction(item[1], function() o:toggleQuickMatchOption(item[2], item[3], item[4]) end)
    end

    o.im.RegisterAction("act_qm_home_kit_prev", function() o:toggleQuickMatchKit(0, -1) end)
    o.im.RegisterAction("act_qm_home_kit_next", function() o:toggleQuickMatchKit(0,  1) end)
    o.im.RegisterAction("act_qm_away_kit_prev", function() o:toggleQuickMatchKit(1, -1) end)
    o.im.RegisterAction("act_qm_away_kit_next", function() o:toggleQuickMatchKit(1,  1) end)
    o.im.RegisterAction("act_qm_home_kit_0", function() o:setQuickMatchKit(0, 0) end)
    o.im.RegisterAction("act_qm_home_kit_1", function() o:setQuickMatchKit(0, 1) end)
    o.im.RegisterAction("act_qm_home_kit_3", function() o:setQuickMatchKit(0, 3) end)
    o.im.RegisterAction("act_qm_away_kit_0", function() o:setQuickMatchKit(1, 0) end)
    o.im.RegisterAction("act_qm_away_kit_1", function() o:setQuickMatchKit(1, 1) end)
    o.im.RegisterAction("act_qm_away_kit_3", function() o:setQuickMatchKit(1, 3) end)

    o.qmEventHandlerId = nil
    
    o.im.RegisterAction("rowClick", function(_, data)
        if data then
            o:rowClick(data)
        end
    end)

    o.nav.AddActionHandler("killScreen", false, nil, function()
        o:finalize()
    end)

    o:_initializeQuickMatchDefaults()
    o.backgroundProcessor:start()
    o:refreshSaveStatus()

    return o
end

function MainHub:rowClick(data)
    if self.qmSetupOpen then
        self:closeQuickMatchSetup()
        self:_hideQuickMatchPreviews(true)
    end

    local index = data.id + 1
    self.currentTabInView = not self.currentTabInView
    if not self.currentTabInView then
        self.currentTab = headlines[index]
        self.ui:handleNav(index)
        -- Quick Match and Volta share one panel: refresh its texts.
        self:publishQuickMatchSetup()
    end
    self:toggleHeadline()
end

function MainHub:_isVoltaTab()
    return self.ui ~= nil and self.ui.currentTab == VOLTA_TAB
end

function MainHub:toggleHeadline(data)  
  local v = {}
  local count = self.currentTabInView and #headlines or 1
  for i = 1, count do
    v[i] = {}
    v[i].data = {}
    local rawName = (not self.currentTabInView) and self.currentTab or headlines[i]
    local displayName = rawName
    if self.qmSetupOpen and (rawName == "Quick Match" or rawName == "Volta") then displayName = "In Match" end
    v[i].data.HeadName = displayName
    --v[i].data.clickAction = "selectleague"
    v[i].data.IsSelected = rawName == self.currentTab
    v[i].data.clickAction = "rowClick"
  end

  self.im.Publish("headlines", v)
end

-- Checks /Save/Save.lua and rebuilds the Career/Tournament tab data +
-- theme to match what's actually on disk right now. Safe to call more
-- than once (e.g. every time the hub is reconstructed) since
-- tabsData.applySave() always rebuilds from untouched canonical tiles
-- rather than mutating whatever happens to be sitting in the tab arrays.
-- Adds the Load tile of every mode that has a save in some slot but is not the newest save's mode.
local function prismLoadTiles(self, newestMode)
    local PS = rawget(_G, "PrismSlots")
    if not (PS and PS.entries) then return end
    local best = {}
    for _, e in pairs(PS.entries()) do
        if type(e) == "table" and (e.mode == "manager" or e.mode == "player" or e.mode == "league" or e.mode == "tourney") then
            local b = best[e.mode]
            if not b or tostring(e.stamp or "") > tostring(b.stamp or "") then best[e.mode] = e end
        end
    end
    local tabOf = tabsData.TAB_OF or { manager = "Tab2", tourney = "Tab3", league = "Tab4" }
    local keep = tabsData.data["default"]
    for mode, e in pairs(best) do
        if mode ~= newestMode then
            tabsData.applySave({ exists = true, mode = mode, teamID = e.club, teamName = safeTeamName(self.loc, e.club) })
            local tab = tabsData.data["default"][tabOf[mode]]
            -- the position tile reads the save that was just read, which is of another mode: left out
            if type(tab) == "table" and tab[2] and tab[2].displayStats then table.remove(tab, 2) end
            -- A tab two modes share (the Career tab: manager and player careers) keeps what it shows and takes this
            -- mode's Load tile before its start-fresh tiles.
            local shared = false
            for m, t in pairs(tabOf) do if m ~= mode and t == tabOf[mode] then shared = true end end
            local cur = keep[tabOf[mode]]
            if shared and type(cur) == "table" and type(tab) == "table" and tab[1] and not tab[1].start then
                local at = #cur + 1
                for i = 1, #cur do if cur[i].start then at = i; break end end
                table.insert(cur, at, tab[1])
            else
                keep[tabOf[mode]] = tab
            end
        end
    end
    tabsData.data["default"] = keep
end

function MainHub:refreshSaveStatus()
    -- The slot index is read first so that the Save tile shows the newest save; a json.load that answers
    -- later refreshes the tile again.
    do local PS = rawget(_G, "PrismSlots"); if PS and PS.readIndex and not PS.indexRead then local me, sync = self, true; pcall(PS.readIndex, function() if not sync then pcall(me.refreshSaveStatus, me) end end); sync = false end end
    validateSave(function(saved, data)
        if not saved then
            tabsData.applySave(nil)
            pcall(prismLoadTiles, self, nil)
            self.themeLeagueID = nil
            self:_refreshVisibleTab()
            return
        end

        -- Only saves belonging to modes that have a tile are surfaced here
        -- (Player Career is back: PrismPro, the Career tab).
        if data.mode ~= "manager" and data.mode ~= "player" and data.mode ~= "tourney" and data.mode ~= "league" then
            tabsData.applySave(nil)
            pcall(prismLoadTiles, self, nil)
            self.themeLeagueID = nil
            self:_refreshVisibleTab()
            return
        end

        local resolvedLeagueID = primeStatsContext(data.mode, data)

        tabsData.applySave({
            exists    = true,
            mode      = data.mode,
            teamID    = data.currentSelectedTeamID,
            teamName  = safeTeamName(self.loc, data.currentSelectedTeamID),
            dateLabel = data.GLOBAL_DATE_PLACEHOLDER
        })

        pcall(prismLoadTiles, self, data.mode)
        self.themeLeagueID = resolvedLeagueID
        self:_refreshVisibleTab()
    end)
end

-- The save check is async, so by the time it resolves the player may
-- already be looking at Tab2/Tab3. If so, re-render the tab in place
-- instead of waiting for the next tab switch to pick up the new data.
function MainHub:_refreshVisibleTab()
    if self.ui and self.ui.currentTab and not self.ui:isMatchTab(self.ui.currentTab) then
        self.ui:handleTabUI({ instant = true })   -- pt-BR (R98e): redrawn in place, no slide (57-careerfirst.patch.js)
    end
end

function MainHub:setModeFlags()
    sessionVars.set("InTourneyMode", self.careerType == "tourney")
    sessionVars.set("InLeagueMode", self.careerType == "league")
    sessionVars.set("InCareerMode", self.careerType == "manager" or self.careerType == "player")
    sessionVars.set("InPlayerCareerMode", self.careerType == "player")
end

-- Pick a recognisable outfield player for the native kit preview. The stock
-- TourneyTeamSelector already treats rating as the canonical way to pick a
-- team's star player, so the same rule is used here. Goalkeeper is avoided
-- unless the squad has no outfield player at all.
function MainHub:_pickQuickMatchPreviewPlayer(teamID)
    if not teamID or teamID <= 0 then return 0 end
    local squadService = self.services and self.services.SquadMgt
    local lineup = (squadService and safeServiceCall(squadService.GetCurrentPlayerLineup, 0, teamID, 0)) or {}
    local bestID, bestRating = 0, -1
    local fallbackID, fallbackRating = 0, -1

    for i = 1, #lineup do
        local player = lineup[i] or {}
        local id = tonumber(player.CARD_ID) or 0
        local rating = tonumber(player.rating) or 0
        if id > 0 then
            if rating > fallbackRating then
                fallbackID, fallbackRating = id, rating
            end
            if player.position ~= "GK" and rating > bestRating then
                bestID, bestRating = id, rating
            end
        end
    end

    return bestID > 0 and bestID or fallbackID
end

function MainHub:_configureQuickMatchPreview(side)
    local preview = self.qmPreview and self.qmPreview[side]
    if not preview then return end

    -- Mirrored full-body presentation. These are intentionally outside the
    -- central team-information column so the screen reads as two players
    -- facing a clean match card instead of four large UI cards.
    local x = side == 0 and -0.91 or 0.91
    local yaw = side == 0 and -14 or 14
    preview:setPosition(x, -0.13)
    preview:setScale(0.90)
    preview:setYaw(yaw)
    preview:setTouchSize(0.31, 0.80)
end

function MainHub:_showQuickMatchPreview(side)
    if not self.qmSetupOpen then return end
    local preview = self.qmPreview and self.qmPreview[side]
    local team = self.qmTeams[side]
    if not preview or not team or not team.id or team.id <= 0 then return end

    local playerID = self:_pickQuickMatchPreviewPlayer(team.id)
    if not playerID or playerID <= 0 then
        preview:hide()
        self.qmPreviewPlayers[side] = 0
        return
    end

    self:_configureQuickMatchPreview(side)
    self.qmPreviewPlayers[side] = playerID
    preview:show(playerID, team.id, self.qmKitType[side] or (side == 0 and 0 or 1))
end

function MainHub:_hideQuickMatchPreviews(cleanup)
    if not self.qmPreview then return end
    for side = 0, 1 do
        local preview = self.qmPreview[side]
        if preview then
            if cleanup then preview:cleanup() else preview:hide() end
        end
    end
end

function MainHub:_readQuickMatchTeam(side, teamID)
    if not teamID or teamID <= 0 then return nil end

    local squadInfo = safeServiceCall(self.services.SquadMgt.GetTeamInfo, teamID) or {}
    local leagueInfo = safeServiceCall(self.services.Country.GetLeagueInfoByTeamId, teamID) or {}
    local leagueID = leagueInfo.id or 0
    local countryInfo = leagueID > 0
        and (safeServiceCall(self.services.Country.GetCountryInfoByLeagueId, leagueID) or {})
        or {}

    return {
        id = teamID,
        name = safeTeamName(self.loc, teamID),
        star = squadInfo.starRating or 0,
        leagueId = leagueID,
        leagueName = leagueInfo.name or "",
        countryId = countryInfo.id or 0
    }
end


local function qmCycleIndex(index, count, direction)
    if not count or count <= 0 then return 1 end
    index = tonumber(index) or 1
    index = index + (direction < 0 and -1 or 1)
    if index < 1 then index = count end
    if index > count then index = 1 end
    return index
end

local function qmFindIndex(list, target, getId)
    for i, value in ipairs(list or {}) do
        local id = getId and getId(value) or value
        if tonumber(id) == tonumber(target) then return i end
    end
    return 1
end

local function qmTeamId(entry)
    if type(entry) == "table" then return tonumber(entry.id or entry.teamId or entry.assetId) end
    return tonumber(entry)
end

function MainHub:_getQuickMatchCountries()
    if self.qmCountries then return self.qmCountries end
    local raw = safeServiceCall(self.services.Country.GetIDs) or {}
    local ids, seen = {}, {}
    for _, entry in pairs(raw) do
        local id = type(entry) == "table" and tonumber(entry.id) or tonumber(entry)
        if id and id > 0 and not seen[id] then
            seen[id] = true
            ids[#ids + 1] = id
        end
    end
    table.sort(ids)
    self.qmCountries = ids
    return ids
end

function MainHub:_getQuickMatchLeagues(countryId)
    local raw = safeServiceCall(self.services.Country.GetLeaguesIDsByCountry, countryId) or {}
    local ids = {}
    for _, entry in ipairs(raw) do
        local id = type(entry) == "table" and tonumber(entry.id) or tonumber(entry)
        if id and id > 0 then ids[#ids + 1] = id end
    end
    return ids
end

function MainHub:_getQuickMatchLeagueTeams(leagueId)
    if not leagueId or leagueId <= 0 then return {} end
    return safeServiceCall(self.services.Team.GetTeams, leagueId, 0, 0, false) or {}
end

function MainHub:_setQuickMatchSelectorFromTeam(side, teamID)
    local team = self:_readQuickMatchTeam(side, teamID)
    if not team then return nil end

    local state = self.qmSelector[side] or {}
    local countries = self:_getQuickMatchCountries()
    state.countryId = team.countryId or 0
    state.countryIndex = qmFindIndex(countries, state.countryId)
    state.leagues = self:_getQuickMatchLeagues(state.countryId)
    state.leagueId = team.leagueId or 0
    state.leagueIndex = qmFindIndex(state.leagues, state.leagueId)
    state.teams = self:_getQuickMatchLeagueTeams(state.leagueId)
    state.teamIndex = qmFindIndex(state.teams, team.id, qmTeamId)
    self.qmSelector[side] = state
    self.qmTeams[side] = team
    return team
end

function MainHub:_initializeQuickMatchDefaults()
    local homeID = tonumber(currentMatch.HomeTeamID) or 0
    local awayID = tonumber(currentMatch.AwayTeamID) or 0
    if homeID <= 0 then homeID = (self.team1 and self.team1.id) or 1 end
    if awayID <= 0 then awayID = (self.team2 and self.team2.id) or 10 end

    local home = self:_setQuickMatchSelectorFromTeam(0, homeID)
    local away = self:_setQuickMatchSelectorFromTeam(1, awayID)
    if home then self:_setQuickMatchTeam(0, home) end
    if away then self:_setQuickMatchTeam(1, away) end
    self:publishQuickMatchSetup()
end

function MainHub:_applyQuickMatchSelectorTeam(side, resetKit)
    local state = self.qmSelector[side]
    if not state or not state.teams then return end
    local entry = state.teams[state.teamIndex]
    local teamID = qmTeamId(entry)
    if not teamID or teamID <= 0 then return end
    local team = self:_readQuickMatchTeam(side, teamID)
    if not team then return end

    -- Re-anchor all profile metadata to the actual selected club. This keeps
    -- country/league/team visually and functionally in the same profile.
    state.countryId = team.countryId or state.countryId
    state.leagueId = team.leagueId or state.leagueId
    if resetKit then
        self.qmKitType[side] = 0
        if side == 0 then currentMatch.HomeKitIndex = 0 else currentMatch.AwayKitIndex = 0 end
    end
    self:_setQuickMatchTeam(side, team)
    self:publishQuickMatchSetup()
end

function MainHub:_toggleQuickMatchCountry(side, direction)
    local countries = self:_getQuickMatchCountries()
    if #countries == 0 then return end
    local state = self.qmSelector[side] or {}
    local index = state.countryIndex or qmFindIndex(countries, state.countryId)

    for _ = 1, #countries do
        index = qmCycleIndex(index, #countries, direction)
        local countryId = countries[index]
        local leagues = self:_getQuickMatchLeagues(countryId)
        for leagueIndex, leagueId in ipairs(leagues) do
            local teams = self:_getQuickMatchLeagueTeams(leagueId)
            if #teams > 0 then
                state.countryId = countryId
                state.countryIndex = index
                state.leagues = leagues
                state.leagueId = leagueId
                state.leagueIndex = leagueIndex
                state.teams = teams
                state.teamIndex = 1
                self.qmSelector[side] = state
                self:_applyQuickMatchSelectorTeam(side, true)
                return
            end
        end
    end
end

function MainHub:_toggleQuickMatchLeague(side, direction)
    local state = self.qmSelector[side]
    if not state then return end
    state.leagues = self:_getQuickMatchLeagues(state.countryId)
    if #state.leagues == 0 then return end
    local index = state.leagueIndex or qmFindIndex(state.leagues, state.leagueId)

    for _ = 1, #state.leagues do
        index = qmCycleIndex(index, #state.leagues, direction)
        local leagueId = state.leagues[index]
        local teams = self:_getQuickMatchLeagueTeams(leagueId)
        if #teams > 0 then
            state.leagueIndex = index
            state.leagueId = leagueId
            state.teams = teams
            state.teamIndex = 1
            self:_applyQuickMatchSelectorTeam(side, true)
            return
        end
    end
end

function MainHub:_toggleQuickMatchTeam(side, direction)
    local state = self.qmSelector[side]
    if not state then return end
    state.teams = self:_getQuickMatchLeagueTeams(state.leagueId)
    if #state.teams == 0 then return end
    state.teamIndex = qmCycleIndex(state.teamIndex or 1, #state.teams, direction)
    self:_applyQuickMatchSelectorTeam(side, true)
end

function MainHub:_setQuickMatchTeam(side, team)
    if not team or not team.id or team.id <= 0 then return end
    self.qmTeams[side] = team

    safeServiceCall(self.services.GameSetup.SetTeam, side, team.id)
    safeServiceCall(self.services.GameSetup.SetTeamIdForNibDisplay, side, team.id)

    if side == 0 then
        currentMatch.HomeTeamID = team.id
        self.team1 = { name = "$Crest", id = team.id }
        self.im.Publish("bnd_team1", self.team1)
    else
        currentMatch.AwayTeamID = team.id
        self.team2 = { name = "$Crest", id = team.id }
        self.im.Publish("bnd_team2", self.team2)
    end

    if self.qmSetupOpen then
        self:_showQuickMatchPreview(side)
    end
end

function MainHub:applyQuickMatchSelection(selected)
    if not selected or not selected.teamRatings then return end
    local side = selected.side == "away" and 1 or 0
    local teamID = selected.teamRatings.teamId
    if not teamID or teamID <= 0 then return end

    self:_setQuickMatchTeam(side, {
        id = teamID,
        name = selected.team or safeTeamName(self.loc, teamID),
        star = selected.teamRatings.starRating or 0,
        leagueId = selected.leagueId or 0,
        leagueName = selected.league or "",
        countryId = selected.countryId or 0
    })
    self:publishQuickMatchSetup()
end

function MainHub:syncQuickMatchTeams()
    local teams = safeServiceCall(self.services.MatchInfo.GetMatchTeams) or {}
    for side = 0, 1 do
        local info = teams[side + 1]
        local id = info and (info.teamId or info.assetId)
        if id and id > 0 then
            self:_setQuickMatchTeam(side, self:_readQuickMatchTeam(side, id))
        end
    end
    self:publishQuickMatchSetup()
end

local function buildQuickMatchKitImage(teamID, kitType)
    if not teamID or teamID <= 0 then return {} end
    return {
        name = "$Kits",
        id = string.format("%s_%s_%s", kitType, teamID, 0)
    }
end

function MainHub:publishQuickMatchSetup()
    self.im.Publish("bnd_qm_default_visible", not self.qmSetupOpen)
    self.im.Publish("bnd_qm_setup_visible", self.qmSetupOpen)
    local text = self:_isVoltaTab() and QM_TEXT.volta or QM_TEXT.quick
    self.im.Publish("bnd_qm_subtitle_home", text.home)
    self.im.Publish("bnd_qm_subtitle_setup", text.setup)
    self.im.Publish("bnd_qm_play_label", text.play)

    local home = self.qmTeams[0] or {}
    local away = self.qmTeams[1] or {}
    local sides = {
        { prefix = "home", data = home, side = 0 },
        { prefix = "away", data = away, side = 1 }
    }

    for _, item in ipairs(sides) do
        local prefix, team, side = item.prefix, item.data, item.side
        local id = team.id or 0
        local kitType = self.qmKitType[side] or (side == 0 and 0 or 1)
        self.im.Publish("bnd_qm_" .. prefix .. "_crest", id > 0 and { name = "$Crest", id = id } or {})
        self.im.Publish("bnd_qm_" .. prefix .. "_country", { name = "$Flag128x128", id = team.countryId or 0 })
        self.im.Publish("bnd_qm_" .. prefix .. "_leaguecrest", { name = "$LeagueLogo", id = team.leagueId or 0 })
        self.im.Publish("bnd_qm_" .. prefix .. "_leaguename", team.leagueName or "")
        self.im.Publish("bnd_qm_" .. prefix .. "_teamname", team.name or "")
        self.im.Publish("bnd_qm_" .. prefix .. "_star", team.star or 0)
        self.im.Publish("bnd_qm_" .. prefix .. "_kitlabel", kitLabel(kitType))
        self.im.Publish("bnd_qm_" .. prefix .. "_kit", buildQuickMatchKitImage(id, kitType))
        for _, variant in ipairs(QM_KIT_TYPES) do
            local isSelected = (kitType == variant)
            self.im.Publish("bnd_qm_" .. prefix .. "_kit" .. variant, buildQuickMatchKitImage(id, variant))
            self.im.Publish("bnd_qm_" .. prefix .. "_kit" .. variant .. "_selected", isSelected)
            self.im.Publish("bnd_qm_" .. prefix .. "_kit" .. variant .. "_dim", not isSelected)
        end
    end
end

function MainHub:openQuickMatchSetup()
    if self.qmSetupOpen then return end

    local homeID = (self.team1 and self.team1.id) or currentMatch.HomeTeamID or 1
    local awayID = (self.team2 and self.team2.id) or currentMatch.AwayTeamID or 10

    -- The clubs shown on the default card are the source of truth. Build the
    -- country + league + team selector profiles from those exact clubs before
    -- revealing the setup state, so the first toggle can never jump to an
    -- unrelated default country/league.
    local home = self:_setQuickMatchSelectorFromTeam(0, homeID)
    local away = self:_setQuickMatchSelectorFromTeam(1, awayID)

    self.qmSnapshot = {
        homeID = homeID,
        awayID = awayID,
        homeKit = currentMatch.HomeKitIndex or 0,
        awayKit = currentMatch.AwayKitIndex or 1
    }

    if home then self:_setQuickMatchTeam(0, home) end
    if away then self:_setQuickMatchTeam(1, away) end
    self.qmKitType[0] = currentMatch.HomeKitIndex or 0
    self.qmKitType[1] = currentMatch.AwayKitIndex or 1

    self.qmSetupOpen = true
    self:_configureQuickMatchPreview(0)
    self:_configureQuickMatchPreview(1)
    self:_showQuickMatchPreview(0)
    self:_showQuickMatchPreview(1)
    self:publishQuickMatchSetup()
    self:toggleHeadline()
end

function MainHub:closeQuickMatchSetup()
    if not self.qmSetupOpen then return end

    local snap = self.qmSnapshot
    self.qmSetupOpen = false
    self:_hideQuickMatchPreviews(false)
    if snap then
        local home = self:_readQuickMatchTeam(0, snap.homeID)
        local away = self:_readQuickMatchTeam(1, snap.awayID)
        if home then self:_setQuickMatchTeam(0, home) end
        if away then self:_setQuickMatchTeam(1, away) end
        self.qmKitType[0] = snap.homeKit
        self.qmKitType[1] = snap.awayKit
        currentMatch.HomeKitIndex = snap.homeKit
        currentMatch.AwayKitIndex = snap.awayKit
    end

    self.qmSnapshot = nil
    self:publishQuickMatchSetup()
    self:toggleHeadline()
end

function MainHub:toggleQuickMatchOption(side, toggleId, direction)
    if not self.qmSetupOpen then return end
    if toggleId == QM_COUNTRY_TOGGLE then
        self:_toggleQuickMatchCountry(side, direction)
    elseif toggleId == QM_LEAGUE_TOGGLE then
        self:_toggleQuickMatchLeague(side, direction)
    elseif toggleId == QM_TEAM_TOGGLE then
        self:_toggleQuickMatchTeam(side, direction)
    end
end

function MainHub:toggleQuickMatchKit(side, direction)
    if not self.qmSetupOpen then return end
    local current = self.qmKitType[side] or (side == 0 and 0 or 1)
    local idx = 1
    for i, value in ipairs(QM_KIT_TYPES) do
        if value == current then idx = i break end
    end
    idx = idx + (direction < 0 and -1 or 1)
    if idx < 1 then idx = #QM_KIT_TYPES end
    if idx > #QM_KIT_TYPES then idx = 1 end
    self.qmKitType[side] = QM_KIT_TYPES[idx]
    if side == 0 then currentMatch.HomeKitIndex = self.qmKitType[side]
    else currentMatch.AwayKitIndex = self.qmKitType[side] end

    local preview = self.qmPreview and self.qmPreview[side]
    if preview then preview:setKit(self.qmKitType[side]) end
    self:publishQuickMatchSetup()
end

function MainHub:setQuickMatchKit(side, kitType)
    if not self.qmSetupOpen then return end
    if kitType ~= 0 and kitType ~= 1 and kitType ~= 3 then return end
    self.qmKitType[side] = kitType
    if side == 0 then currentMatch.HomeKitIndex = kitType
    else currentMatch.AwayKitIndex = kitType end

    local preview = self.qmPreview and self.qmPreview[side]
    if preview then preview:setKit(kitType) end
    self:publishQuickMatchSetup()
end

function MainHub:PlayMatch()
    if not self.qmSetupOpen then
        self:openQuickMatchSetup()
        return
    end

    local home = self.qmTeams[0]
    local away = self.qmTeams[1]
    if not (home and home.id and away and away.id) then return end

    -- Persist the exact inline selection before leaving MainHub. The next
    -- screen is only a final two-button confirmation screen; it must not
    -- reconstruct or replace the chosen teams/kits.
    self.qmSetupOpen = false
    self:_setQuickMatchTeam(0, home)
    self:_setQuickMatchTeam(1, away)
    currentMatch.HomeTeamID = home.id
    currentMatch.AwayTeamID = away.id
    currentMatch.HomeLeagueID = home.leagueId
    currentMatch.AwayLeagueID = away.leagueId
    currentMatch.HomeCountryID = home.countryId
    currentMatch.AwayCountryID = away.countryId
    currentMatch.HomeKitIndex = self.qmKitType[0] or 0
    currentMatch.AwayKitIndex = self.qmKitType[1] or 1
    currentMatch.Side = 0
    currentMatch.isUserSideHome = 0
    -- One-shot: only the match launched right now from the Volta tab is Volta.
    currentMatch.F16Volta = nil   -- locked variant: never Volta
    currentSelectedTeamID = home.id

    safeServiceCall(self.services.GameSetup.SetTeam, 0, home.id)
    safeServiceCall(self.services.GameSetup.SetTeam, 1, away.id)
    safeServiceCall(self.services.GameSetup.SetTeamIdForNibDisplay, 0, home.id)
    safeServiceCall(self.services.GameSetup.SetTeamIdForNibDisplay, 1, away.id)
    safeServiceCall(self.services.GameSetup.SetPreferredKitId, 0, home.id * 4096 + currentMatch.HomeKitIndex)
    safeServiceCall(self.services.GameSetup.SetPreferredKitId, 1, away.id * 4096 + currentMatch.AwayKitIndex)
    safeServiceCall(self.services.GameSetup.CommitKitSelect)

    self.qmSnapshot = nil
    self:_hideQuickMatchPreviews(true)
    self.nav.Event(nil, "evt_enter_qm")
end

-- "Load Career"/"Load Tournament" tile. Mirrors the original
-- MainMenu/MenuCM/PlayHub.lua's act_careermodeload handler exactly:
-- resetContextData -> set "loadcareer" -> set the mode flags -> fire
-- evt_enter_cm directly. This is deliberately NOT the evt_show_overlay +
-- TeamSelector.vvm path enterCareerMode uses below — that path renders
-- the team-selection grid screen, which is correct for a fresh career
-- (the player needs to see it to pick a team) but wrong for a load,
-- since the team is already decided by the save. evt_enter_cm instead
-- drives MainHub.nav straight into the "EnterCM" state (the external
-- TeamSelect.nav), where TeamSelect.lua's own loadmode branch (driven by
-- the "loadcareer" flag we set here) skips generation, calls
-- LoadSave:loadSavedGame(), and proceeds straight into the career —
-- without ever painting the selection grid.
function MainHub:loadCareerMode(careerType, prismPicked)
    self.careerType = careerType
    -- The slot screen comes first (PrismSlots); the slot picked is then loaded the stock way below.
    do
        local PS = rawget(_G, "PrismSlots")
        if PS and PS.pick and not prismPicked then
            pcall(PS.readIndex)
            local okF, free = pcall(PS.freeCount)
            if okF and type(free) == "number" and free < PS.COUNT then
                local me = self
                PS.pick({ mode = "load", popup = self.FCPopup, loc = self.loc, done = function(n)
                    PS.active = n
                    me:loadCareerMode(careerType, true)
                end })
                return
            end
        end
    end

    validateSave(function(proceed, data)
        if not proceed then
            self.FCPopup:getResponse("No save data found", { "Go back" }, function() end)
            return
        end

        -- A slot of another mode loads as that mode.
        if prismPicked and data.mode ~= careerType and (data.mode == "manager" or data.mode == "player" or data.mode == "league" or data.mode == "tourney") then
            careerType = data.mode
            self.careerType = careerType
        end
        if data.mode ~= careerType then
            self.FCPopup:getResponse(
                "Your saved game is for a different mode",
                { "Go back" },
                function() end
            )
            return
        end

        sessionVars.setContext(careerType)
        sessionVars.resetContextData(careerType)
        -- this career's slot and identity
        do local PS = rawget(_G, "PrismSlots"); if PS and PS.active and PS.adopt then pcall(PS.adopt, PS.active, sessionVars) end end

        -- League Mode's Processor intentionally caches only one league, so its
        -- selected league must be available before TeamSelect step 2 runs.
        -- Manager/Tournament discover their broader cache scope independently.
        if careerType == "league" then
            currentSelectedTeamID = data.currentSelectedTeamID
            sessionVars.set("currentSelectedTeamID", data.currentSelectedTeamID)
            sessionVars.set("currentUserLeagueID", data.currentLeagueID)
        end

        sessionVars.set("loadcareer", true)
        self:setModeFlags()

        self.nav.Event(nil, "evt_enter_cm")
    end)
end

-- Career / Tournament / League tile (see
-- mainMenuTabsData.lua) — start fresh, or resume an already-live
-- in-memory session from earlier in this app session. Goes through the
-- TeamSelector overlay so the player can actually pick a team; never
-- touches the on-disk save (that's loadCareerMode above).
function MainHub:enterCareerMode(careerType)
    self.careerType = careerType
    sessionVars.setContext(careerType)

    local screen
    if careerType == "tourney" then
        screen = "/flows/mainflow/gamemodes/Liga/Screens/TourneyTeamSelector/TeamSelector.vvm"
    elseif careerType == "league" then
        screen = "/flows/mainflow/gamemodes/Liga/Screens/LeagueTeamSelector/TeamSelector.vvm"
    else
        screen = "/flows/mainflow/gamemodes/Liga/Screens/TeamSelector/TeamSelector.vvm"
    end

    if sessionVars.get("CareerMode") then
        self.FCPopup:getResponse("You have a current career underway, Continue?",
        { "Yes", "Take Me Back", "New Career" },
        function(clickResponse)
            if clickResponse == 1 then
                self:setModeFlags()
                self.nav.Event(nil, "evt_enter_cm")

            elseif clickResponse == 3 then
                sessionVars.resetContextData(careerType)
                sessionVars.set("loadcareer", nil)
                self.nav.Event(nil, "evt_show_overlay", {
                    vvm = screen,
                    data = { nav = self.nav, careertype = careerType }
                })
                self:setModeFlags()
            end
        end)
    else
        sessionVars.set("loadcareer", nil)
        self.nav.Event(nil, "evt_show_overlay", {
            vvm = screen,
            data = { nav = self.nav, careertype = careerType }
        })
        self:setModeFlags()
    end
end

function MainHub:animateTabButtons(tabsNum, btnTabsXConfig, direction, animationType, startOrTargetX, callback)
    if not tabsNum or not btnTabsXConfig or tabsNum < 1 or not startOrTargetX then
        if callback then callback() end
        return
    end

    self.backgroundProcessor:removeAnimTrack("btnAnim")
    self.isBtnAnimating = true

    local trackInterval = animationType == "fadeOut" and 0.033 or 0.016
    local steps = math.max(1, math.floor(0.05 / trackInterval))

    local buttonOrder = {}
    for i = 1, tabsNum do
        buttonOrder[i] = direction == 1 and i or (tabsNum + 1 - i)
    end

    local step = 0
    local totalSteps = tabsNum * steps
    local bp = self.backgroundProcessor

    bp:registerAnimTrack("btnAnim", function()
        if not self.isBtnAnimating then
            bp:removeAnimTrack("btnAnim")
            if callback then callback() end
            return
        end

        step = step + 1

        if step > totalSteps then
            bp:removeAnimTrack("btnAnim")
            self.isBtnAnimating = false
            if callback then callback() end
            return
        end

        local btnIdx = math.floor((step - 1) / steps) + 1
        local stepInB = (step - 1) % steps + 1
        local bIdx = buttonOrder[btnIdx]

        local startX  = animationType == "fadeOut" and btnTabsXConfig[bIdx] or startOrTargetX
        local targetX = animationType == "fadeOut" and startOrTargetX or btnTabsXConfig[bIdx]

        local t = stepInB / steps
        local ePT = 1 - (1 - t) * (1 - t)
        local currX = startX + (targetX - startX) * ePT

        self.im.Publish("bnd_btnX" .. bIdx, math.floor(currX + 0.5))

        if stepInB == steps then
            self.im.Publish("bnd_btnX" .. bIdx, targetX)
        end
    end, trackInterval)
end

function MainHub:animateSwipeTabs(startX, targetX, callback)
    if startX == targetX then
        if callback then callback() end
        return
    end

    self.backgroundProcessor:removeAnimTrack("swipeAnim")

    local trackInterval = 0.016
    local duration = 0.12
    local elapsed = 0

    local bp = self.backgroundProcessor

    bp:registerAnimTrack("swipeAnim", function()
        elapsed = elapsed + trackInterval
        local t = math.min(elapsed / duration, 1)
        local ePT = 1 - (1 - t) * (1 - t)

        local currX = startX + (targetX - startX) * ePT
        self.im.Publish("bnd_tabsPosX", math.floor(currX + 0.5))

        if t >= 1 then
            self.im.Publish("bnd_tabsPosX", targetX)
            bp:removeAnimTrack("swipeAnim")
            if callback then callback() end
        end
    end, trackInterval)
end

function MainHub:update(elapsedTime)
    if self.backgroundProcessor then
        self.backgroundProcessor:update(elapsedTime)
    end
end

function MainHub:finalize()
    self:_hideQuickMatchPreviews(true)
    if self.backgroundProcessor then
        self.backgroundProcessor:removeAnimTrack("btnAnim")
        self.backgroundProcessor:removeAnimTrack("swipeAnim")
        self.backgroundProcessor:finalize()
        self.backgroundProcessor = nil
    end

    self.im.UnregisterAction(ACT_MATCH_PLAY)
    self.im.UnregisterAction(ACT_QM_CANCEL)
    local qmActions = {
        "act_qm_home_team_prev", "act_qm_home_team_next", "act_qm_away_team_prev", "act_qm_away_team_next",
        "act_qm_home_league_prev", "act_qm_home_league_next", "act_qm_away_league_prev", "act_qm_away_league_next",
        "act_qm_home_country_prev", "act_qm_home_country_next", "act_qm_away_country_prev", "act_qm_away_country_next",
        "act_qm_home_kit_prev", "act_qm_home_kit_next", "act_qm_away_kit_prev", "act_qm_away_kit_next",
        "act_qm_home_kit_0", "act_qm_home_kit_1", "act_qm_home_kit_3",
        "act_qm_away_kit_0", "act_qm_away_kit_1", "act_qm_away_kit_3"
    }
    for _, action in ipairs(qmActions) do self.im.UnregisterAction(action) end
    if self.qmEventHandlerId then
        self.services.EventManagerService.UnregisterHandler(self.qmEventHandlerId)
        self.qmEventHandlerId = nil
    end
    local qmBindings = {
        "bnd_qm_default_visible", "bnd_qm_setup_visible",
        "bnd_qm_subtitle_home", "bnd_qm_subtitle_setup", "bnd_qm_play_label",
        "bnd_qm_home_crest", "bnd_qm_away_crest", "bnd_qm_home_country", "bnd_qm_away_country",
        "bnd_qm_home_leaguecrest", "bnd_qm_away_leaguecrest", "bnd_qm_home_leaguename", "bnd_qm_away_leaguename",
        "bnd_qm_home_teamname", "bnd_qm_away_teamname", "bnd_qm_home_star", "bnd_qm_away_star",
        "bnd_qm_home_kit", "bnd_qm_away_kit", "bnd_qm_home_kitlabel", "bnd_qm_away_kitlabel"
    }
    for _, binding in ipairs(qmBindings) do self.im.Unsubscribe(binding) end

    self.im.Unsubscribe("bnd_menu_bg")
    self.im.Unsubscribe("bnd_team1")
    self.im.Unsubscribe("bnd_team2")
    self.im.Unsubscribe("bnd_rectColor")

    if self.ui then self.ui:reset() end
end

return MainHub