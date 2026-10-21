-- Diagnostics (Trace.patch.js): PRISM_CRUMB(text) writes one "crumb: <text>" line to preview.log.
rawset(_G, "PRISM_CRUMB", function(s) local f = rawget(_G, "F16_SVC"); if f then pcall(function() f.Cmd("log:crumb: " .. tostring(s)) end) end end)
-- MatchSelect.lua  (Liga)  [unified animation tracks]

--

-- WHAT CHANGED vs the previous version:

--   All six animation timer-chains (date swipe, deadline, matchday, news,

--   tab-button slide, tab swipe) have been converted to BackgroundProcessor

--   animation tracks (Phase 1.5).  Every animation is now driven by the

--   SAME single timer that already drives BP tasks.

--

-- REMOVED per-animation Timer objects:

--   self.dateTimer, self.deadlineTimer, self.matchdayTimer,

--   self.swipeTimer, self.btnTimer, self.newsTimer

--

-- REMOVED from Liga:update():

--   All individual timer:update() calls — BP.update() handles everything.

--

-- REMOVED from Liga:finalize():

--   All individual timer:finalize() calls — replaced with removeAnimTrack().

--

-- CHANGED setAnimating() usage:

--   Passing pauseMode=true to BP used to freeze all BP tasks while an

--   animation played.  With tracks inside BP, that would kill the animation.

--   All calls now use setAnimating(true, false) or are simply omitted

--   (registerAnimTrack auto-sets isAnimating on BP).

--

-- PRESERVED completely:

--   All animation math, easing, timing values, phase boundaries, publish

--   sequences, callback chains, and cancellation logic are byte-for-byte

--   equivalent to the original. Only the scheduling mechanism changes.



local SeasonInit, PlayerAge, playerData, Brain, LiveTransfers, Squads,

      AITransfers, CareerFriendlies, glInstancePasser, Timer, FCPopup, Date,

      Modes, NewsCenter, UI, sessionVars, DateUtils, BackgroundProcessor,

      TaskRow, MatchSimulator, MatchHandler, TeamData, TeamStats, Save,

      UIManager, Serializer, LeagueNames, Callback, Notification,

      PlayerCareer, NativePlayerData = ...



local Liga = {}

gamemode = "careerMode"

local TeamList      = sessionVars.get("TeamList")

local ACT_ADVANCE   = "act_advance"

-- League Mode reuses the match/calendar engine, but transfer-deadline days
-- are Career-only and should behave as ordinary dates here.
local function isDeadlineActive()
    return not sessionVars.get("InLeagueMode") and Date:isDeadline()
end

local ACT_EXIT      = "act_exit"

local BND_REALTIME  = "bnd_realtime"

local PROGRESS      = "act_progressdate"

local BND_DATE1     = "bnd_date1"

local BND_DATE2     = "bnd_date2"

local BND_DATE3     = "bnd_date3"

local BND_IS_DATE_SIM     = "bnd_isDateSim"

local BND_IS_NOT_DATE_SIM = "bnd_isNotDateSim"

local UIbnds = {"bnd_headline","bnd_likeNo","bnd_commentNo","bnd_newsDate",

                "bnd_sourceImg","bnd_sourceName"}



-- ── Helpers ────────────────────────────────────────────────────────────────



local function ordinal(n)

    local suffix = "TH"

    if n % 100 < 11 or n % 100 > 13 then

        local d = n % 10

        if     d == 1 then suffix = "ST"

        elseif d == 2 then suffix = "ND"

        elseif d == 3 then suffix = "RD"

        end

    end

    return tostring(n) .. suffix

end



local function getMatchupInfo(daysToFixture, matchType)

    if daysToFixture == 0 then return "Matchday" end

    return daysToFixture <= 7

        and ("Next Fixture in " .. daysToFixture

             .. (daysToFixture > 1 and " days" or " day"))

        or "No upcoming fixtures"

end



local function publishMatchDetails(self, daysToFixture, matchDateStr,

        homeID, awayID, homeName, awayName, matchType, lgId, round)

    if not self.im then return end

    UIManager.setTheme(self.im, nil, lgId)

    local matchDateLabel = daysToFixture <= 7

        and self.DateUtils:formatDateAsMonthDay(matchDateStr) or ""

    local leagueLabel    = daysToFixture <= 7

        and ((LeagueNames[lgId]

             or (self.loc.LocalizeString("LeagueName_Abbr15_" .. lgId))) .. (round and " " .. round or "")) or ""

    local matchTag = daysToFixture <= 7

        and (matchType == "League"      and "League"   or

             matchType == "Friendly"    and "#Friendly" or

             matchType == "Competition" and "#Cup"      or "#Match")

        or ""

    self.HomeCrest = self.HomeCrest or { id = 0 }

    self.AwayCrest = self.AwayCrest or { id = 0 }

    self.HomeCrest.id = homeID or 0

    self.AwayCrest.id = awayID or 0

    self.im.Publish("bnd_matchup_label",  getMatchupInfo(daysToFixture, matchType or "League"))

    self.im.Publish("bnd_matchdate_label",daysToFixture == 0 and "Today" or matchDateLabel)

    self.im.Publish("bnd_league_label",   leagueLabel)

    self.im.Publish("matchleague",        daysToFixture <= 7

        and {name="$LeagueLogo", id=lgId} or {})

    self.im.Publish("bnd_matchtag",       matchTag)

    self.im.Publish("bnd_home_crest",     daysToFixture <= 7 and self.HomeCrest or {})

    self.im.Publish("bnd_away_crest",     daysToFixture <= 7 and self.AwayCrest or {})

    self.im.Publish("bnd_home_name",      daysToFixture <= 7 and (homeName or ""):upper() or "")

    self.im.Publish("bnd_away_name",      daysToFixture <= 7 and (awayName or ""):upper() or "")

end



local function findCurrentDayMatch(self, dateStr, currentSelectedTeamID)

    local standardDate = self.DateUtils:parseDate(dateStr or "01/08/25")

    if not standardDate then return nil, nil, nil end

    local currentTime = os.time({

        day=standardDate.day, month=standardDate.month, year=standardDate.year,

        hour=0, min=0, sec=0

    })

    local matches = sessionVars.get("MatchData") or {}

    for i, match in ipairs(matches) do

        if (match.matchType == "League" or match.matchType == "Friendly"

        or  match.matchType == "Competition")

        and (match.homeID == currentSelectedTeamID

        or   match.awayID == currentSelectedTeamID) then

            local matchDateStr = self.DateUtils:convertMatchDateToStandard(match.date)

            if matchDateStr then

                local matchDate = self.DateUtils:parseDate(matchDateStr)

                if matchDate then

                    local matchTime = os.time({

                        day=matchDate.day, month=matchDate.month, year=matchDate.year,

                        hour=0, min=0, sec=0

                    })

                    if matchTime == currentTime then

                        return match.homeID, match.awayID, i

                    end

                end

            end

        end

    end

    return nil, nil, nil

end



local function daysToNextMatch(self, currentDateStr, currentSelectedTeamID)

    local currentDate = self.DateUtils:parseDate(currentDateStr or "01/08/25")

    if not currentDate then

        return nil, nil, nil, nil, nil, "Invalid current date"

    end

    local currentTime = os.time({

        day=currentDate.day, month=currentDate.month, year=currentDate.year,

        hour=0, min=0, sec=0

    })

    local matches        = sessionVars.get("MatchData") or {}

    local nextMatchTime  = nil

    local nextMatchDateStr= nil
    
    local round = nil

    local homeID, awayID, matchType, lgId



    for i, match in ipairs(matches) do

        if (match.matchType == "League" or match.matchType == "Friendly"

        or  match.matchType == "Competition")

        and (match.homeID == currentSelectedTeamID

        or   match.awayID == currentSelectedTeamID) then

            local matchDateStr = self.DateUtils:convertMatchDateToStandard(match.date)

            if matchDateStr and self.DateUtils:isValidMatchDate(match.date) then

                local matchDate = self.DateUtils:parseDate(matchDateStr)

                if matchDate then

                    local matchTime = os.time({

                        day=matchDate.day, month=matchDate.month, year=matchDate.year,

                        hour=0, min=0, sec=0

                    })

                    if matchTime >= currentTime

                    and (not nextMatchTime or matchTime < nextMatchTime) then

                        nextMatchTime    = matchTime

                        nextMatchDateStr = matchDateStr

                        homeID           = match.homeID

                        awayID           = match.awayID

                        lgId             = match.leagueID

                        matchType        = match.matchType
                        
                        round = match.matchRound

                    end

                end

            end

        end

    end



    if not nextMatchTime then

        return nil, nil, nil, getTeamLeague(currentSelectedTeamID), nil,

               "No future match dates found"

    end

    local daysDiff = math.floor((nextMatchTime - currentTime) / 86400)

    return daysDiff, nextMatchDateStr, homeID, awayID, lgId, matchType, round, nil

end



local function formatDeadlineColor(minutes)

    return minutes <= 60 and "0xFF0D00" or "0xFFE300"

end



-- ── Module-level state ─────────────────────────────────────────────────────



ligaId         = 1

loaded         = loaded or "no"

mode           = 1

currentMatch   = { HomeTeamID=0, AwayTeamID=0, HomeKitIndex=0, AwayKitIndex=1 }

local matchesPlayed = 0

local matchday      = false



-- ── Constructor ────────────────────────────────────────────────────────────



--- Writes "load: <msg>" to preview.log through F16Service (libpv stamps each line in ms): the career load's timeline.
local function prismLoadMark(msg)
    local f = rawget(_G, "F16_SVC")
    if f and f.Cmd then pcall(f.Cmd, "log:load: " .. msg) end
end
local prismFirstFrame = true
function Liga:new(init)
    -- Back on the hub: the cards of a match that was left unrecorded do not stand.
    do local S = rawget(_G, "PRISM_SUSP"); if S and S.discardPending then pcall(S.discardPending) end end
    prismLoadMark("hub: building")

    local o = init or {}

    setmetatable(o, self)

    self.__index = self

    initTheme(o.im)
    
    sessionVars.set("CareerMode",    true)

    o.services = {

        settingsService       = o.api("SettingsService"),

        SquadManagementService= o.api("SquadMgtService"),

        BrowserService        = o.api("BrowserService"),

    }

    -- Player development: bind F16Service, take over a loaded save or a new career, track the user's league.
    do local CD = rawget(_G, "CareerDev"); if CD then pcall(CD.bind, o.api, { SquadMgtService = o.services.SquadManagementService }, sessionVars); pcall(CD.queueLeagueTeams) end end

    -- the career setup's settings
    do local PSU = rawget(_G, "PrismSetup"); if PSU and PSU.apply then PSU.bind(sessionVars); pcall(PSU.apply, o.api) end end
    -- Retirements and youth players: a new career (or a save without youths) gets its academy and pool.
    do local Y = rawget(_G, "PrismYouth"); if Y and Y.bind then local ok, err = pcall(Y.bind, sessionVars); if not ok and Y.log then Y.log("bind failed: " .. tostring(err)) end end end
    -- Player Career: the user's own player (a created player's build is applied here, after CareerDev and PrismYouth)
    do local PRO = rawget(_G, "PrismPro"); if PRO and PRO.bind then local ok, err = pcall(PRO.bind, sessionVars, { SquadMgtService = o.services.SquadManagementService }, o.loc); if not ok and PRO.log then PRO.log("bind failed: " .. tostring(err)) end end end

    -- BSS is process-local. Rebuild the native match override registry from
    -- the career save every time the home hub is constructed.
    -- The stock sync below clears the engine's override table: mark CareerDev's copy of it stale first.
    do local CD = rawget(_G, "CareerDev"); if CD and CD.overridesStale then CD.overridesStale() end end
    if NativePlayerData and NativePlayerData.SyncRuntimeOverrides then
        local ok, synced, detail = pcall(
            NativePlayerData.SyncRuntimeOverrides,
            o.services.SquadManagementService,
            rawget(_G, "CAREER_PLAYER_OVERRIDES") or {})
        if not ok or not synced then
            pcall(NativePlayerData.Log,
                "RUNTIME_OVERRIDE_SYNC_FAIL " .. tostring(ok and detail or synced))
        end
    end



    local origNav = o.nav.Event

    o.nav.Event = (function(c1, c2, c3) origNav(c1, c2, c3)

       if Notification and Notification.update then

         Notification:update(c2)

       end

       if TaskRow and TaskRow.update then

         TaskRow:update(c2)

       end

     end)

    local displaynews = (sessionVars.get("InCareerMode") or sessionVars.get("InLeagueMode"))
and (not displayMatchdayFixtures)
    o.save         = Save:new({api = o.api, Timer = Timer})

    o.save:openBrowser()



    o.backgroundProcessor = BackgroundProcessor:new({

        im           = o.im,

        save         = o.save,

        Timer        = Timer,

        idleTimeout  = 0,

        maxFrameTime = 0,

        debugOverlay = {

            enabled = false,

            publish = function(data) end,

        },

    })



    o.passedInstance = glInstancePasser:loadInstance()

    o.round          = 1

    o.test           = o.passedInstance.test

    o.allTeams       = o.passedInstance.allTeams

    o.brain          = Brain:new()

    o.squads         = Squads:new({services = o.services})

    o.transferSystem = LiveTransfers:new({

        transferHandler = function(...) return o:_handleTransfer(...) end

    })

    o.FCPopup    = FCPopup:new({nav = o.nav})

    -- Player Career state manager. Constructed unconditionally (the module

    -- is a no-op when InPlayerCareerMode is false). It needs the same

    -- services MatchSelect already wired up.

    o.playerCareer = PlayerCareer:new({

        nav      = o.nav,

        loc      = o.loc,

        services = o.services,

    })

    -- Expose via global so AITransfers.lua's batchTransfers can call

    -- autoResolveTeammateOffer without wiring PlayerCareer through the

    -- entire deps chain. This mirrors how currentSelectedTeamID,

    -- GLOBAL_FUNDS, transferredPlayers etc. are already globals.

    g_PlayerCareer = o.playerCareer

    o.Modes      = Modes:new({nav=o.nav, loc=o.loc, api=o.api})

    o.SeasonInit = SeasonInit:new({

        api=o.api, nav=o.nav, brain=Brain, save=o.save, Timer=Timer, Modes=o.Modes

    })

    o.Date       = Date:new({haltAdvance=function() o:NoMatch() end, Modes=o.Modes, api=o.api})

    o.DateUtils  = DateUtils:new()

    o.uiValues   = {80, 390, 700}

    o.newsCenter = NewsCenter:new({im=o.im, loc=o.loc})

    o.serializer = Serializer:new({

        sessionVars=sessionVars, nav=o.nav, Date=o.Date, Timer=Timer,

        bgProcessor=o.backgroundProcessor,

        startSave = function(clbk) o:startSave(clbk) end,
        
        updateSave = function(msg, btn, clbk) o:updateSave(msg, btn, clbk) end

    })
    rawset(_G, "PRISM_SERIALIZER", o.serializer)   -- for the autosave
    -- The career's save slot (PrismSlots.active; nil: never saved). The hub's popup and localisation are
    -- what the Save card's slot screen shows on.
    do local PS = rawget(_G, "PrismSlots"); if PS and PS.resume then pcall(PS.resume, sessionVars); PS.hubPopup = o.FCPopup; PS.hubLoc = o.loc end end



    o.models = {

        PlayerAge  = PlayerAge:new({api=o.api, loc=o.loc, nav=o.nav}),

        playerData = playerData:new({api=o.api, loc=o.loc, nav=o.nav}),

        AITransfers= AITransfers:new({

            services=o.services, loc=o.loc, nav=o.nav,

            squads=o.squads, save=o.save

        }),

    }

    o.TeamStats    = TeamStats:new({loc = o.loc})

    o.Notification = Notification:new({im = o.im, nav = o.nav})



    -- Wrap UI registration methods to capture user interactions.

    local origRA = o.im.RegisterAction

    o.im.RegisterAction = function(actionName, handler)

        origRA(actionName, function(actionName, data)

            o:onUserInteraction()

            if handler then handler(actionName, data) end

        end)

    end

    local origRDA = o.im.RegisterDataAction

    o.im.RegisterDataAction = function(binding, actionName, handler)

        origRDA(binding, actionName, function(binding, actionName, data)

            o:onUserInteraction()

            if handler then handler(binding, actionName, data) end

        end)

    end

    local origAAH = o.nav.AddActionHandler

    o.nav.AddActionHandler = function(name, param1, param2, handler)

        origAAH(name, param1, param2, function()

            o:onUserInteraction()

            if handler then handler() end

        end)

    end



    o.ui = UI:new({

        im                 = o.im,

        nav                = o.nav,

        backgroundProcessor= o.backgroundProcessor,

        playerData         = playerData,

        swipeTabs          = function(sx, tx, cb) o:_swipeTab(sx, tx, cb) end,

        animateTabButtons  = function(tn, cfg, dir, atype, sx, cb)

            o:_animateTabButtons(tn, cfg, dir, atype, sx, cb)

        end,

        TeamStats  = o.TeamStats,

        serializer = o.serializer,

    })



    o.UItasks  = TaskRow.new({im=o.im, nav=o.nav})

    o.nav.AddActionHandler("Test", false, nil, function() o:testScript() end)



    o.currentOptions    = o.services.settingsService.GetCurrentOptions()

    o.Banner            = { name="$Tab_CupInfo", id=0 }

    o.HomeCrest         = { name="$Crest", id=0 }

    o.AwayCrest         = { name="$Crest", id=0 }

    o.dateYPositions    = {-100, -20, 60}

    o.isDateSim         = false

    o.isAutoAdvancing   = false

    -- Animation state flags — set true when a track starts, false on completion.

    -- These are Liga-level flags; BP.isAnimating reflects ANY active track.

    o.isAnimating           = false

    o.isMatchdayAnimating   = false

    o.isSwipeAnimating      = false

    o.isBtnAnimating        = false

    o.isNewsAnimating       = false

    -- NOTE: individual timer OBJECTS are gone.  BP tracks replace them.

    o.transfersDoneForDate  = {}

    o.lastTransferDate      = nil

    o.swipeX                = 0

    o.lastInteractionTime   = os.clock()

    o.simMode               = false

    o.deadlineTime          = sessionVars.get("deadlineTime") or 10 * 60



    o.matchSimulator = MatchSimulator:new({

        DateUtils             = o.DateUtils,

        sessionVars           = sessionVars,

        services              = o.services,

        currentSelectedTeamID = currentSelectedTeamID,

        Modes                 = o.Modes,

    })

    o.matchHandler = MatchHandler:new({

        DateUtils   = o.DateUtils,

        sessionVars = sessionVars,

    })



    -- ── Register background tasks ─────────────────────────────────────────

    if not sessionVars.get("InLeagueMode") then
        o.backgroundProcessor:registerIntervalTask(

            function() o:processTransfersTask() end,

            "Transfers", 0.5, 1, true

        )

        o.backgroundProcessor:registerIntervalTask(

            function() o:processScoutingTask() end,

            "Scouting", 0.5, 1, true

        )
    end

    if displaynews then

        o.backgroundProcessor:registerIntervalTask(function()

            local rand = math.random(1, 10)

            local dir  = rand < 6 and 1 or -1

            o:displayNews(dir)

        end, "newsUpdate", 5, 5, true)

    end



    -- Seed RNG

    math.randomseed(os.clock() * 1352 + os.time())

    local random2 = math.random(5)



    o.im.Subscribe("bnd_ads", function()

        o.Banner.id = random2

        o.im.Publish("bnd_ads", o.Banner)

    end)



    o.publishDate1 = function()

        local nextDate = o.DateUtils:getNextDay(GLOBAL_DATE_PLACEHOLDER or "01/08/25")

        o.im.Publish(BND_DATE1, o.DateUtils:formatDateAsDayName(nextDate))

    end

    o.publishDate2 = function()

        if isDeadlineActive() then

            o.im.Publish(BND_DATE2, "DEADLINE DAY")

        elseif displayMatchdayFixtures then

            o.im.Publish(BND_DATE2, "")

        else

            local currentDate = o.DateUtils:parseDate(GLOBAL_DATE_PLACEHOLDER or "01/08/25")

            o.im.Publish(BND_DATE2, o.DateUtils:formatDateAsDayName(currentDate))

        end

    end

    o.publishDate3 = function()

        local prevDate = o.DateUtils:getPreviousDay(GLOBAL_DATE_PLACEHOLDER or "01/08/25")

        o.im.Publish(BND_DATE3, o.DateUtils:formatDateAsDayName(prevDate))

    end



    o.im.Subscribe("bnd_dateAA3",      function() o.im.Publish("bnd_dateAA3", 1)  end)

    o.im.Subscribe("dateTS1",          function() o.im.Publish("dateTS1", 20)      end)

    o.im.Subscribe("displaynews",      function() o.im.Publish("displaynews", displaynews) end)

    o.im.Subscribe("dateTS2",          function() o.im.Publish("dateTS2", 40)      end)

    o.im.Subscribe("bnd_showAdvanceBtn",function() o.im.Publish("bnd_showAdvanceBtn", true) end)

    o.im.Subscribe(BND_DATE1,          o.publishDate1)

    o.im.Subscribe(BND_DATE2,          o.publishDate2)

    o.im.Subscribe(BND_DATE3,          o.publishDate3)

    o.im.Subscribe(BND_IS_DATE_SIM,    function() o:dateAnim() end)

    o.im.Subscribe("bnd_isdeadline",   function() o.im.Publish("bnd_isdeadline", isDeadlineActive()) end)

    o.im.Subscribe("bnd_deadlinetime", function() o:publishDeadlineTime() end)

    o.im.Subscribe("bnd_deadlinecolor",function() o.im.Publish("bnd_deadlinecolor", formatDeadlineColor(o.deadlineTime)) end)

    o.im.Subscribe(BND_IS_NOT_DATE_SIM,function() o:dateAnim() end)

    o.im.Subscribe("bnd_epl_visible",  function() o:publishBg() end)

    o.im.Subscribe("bnd_home_crest",   function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_away_crest",   function() o:publishFinishLabel() end)

    o.im.Subscribe("matchleague",      function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_home_name",    function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_away_name",    function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_homeRank",     function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_homeRankX",    function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_awayRank",     function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_awayRankX",    function() o:publishFinishLabel() end)

    o.im.Subscribe("simmode",          function() o:toggleSim("init") end)



    o.crestAnimBnds = {"crestsizeW","crestsizeH","cresthomeX","crestawayX","crestalpha"}

    for i = 1, #o.crestAnimBnds do

        o.im.Subscribe(o.crestAnimBnds[i], function()

            o.im.Publish("crestsizeW",  55)

            o.im.Publish("crestsizeH",  55)

            o.im.Publish("cresthomeX", -230)

            o.im.Publish("crestawayX", -160)

            o.im.Publish("crestalpha",   1)

        end)

    end



    o.im.RegisterAction(ACT_ADVANCE, function(actionName, data)

        if data then o:PlayMatch(data) end

    end)

    o.im.RegisterAction(ACT_EXIT,    function() o:exitCareer() end)

    o.im.RegisterAction("act_togglesim", function() o:toggleSim() end)



    o.im.Subscribe("bnd_finish_label",   function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_date_label",     function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_matchup_label",  function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_matchdate_label",function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_matchtag",       function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_league_label",   function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_advance_label",  function() o:publishFinishLabel() end)

    o.im.Subscribe("bnd_month_label",    function() o:publishFinishLabel() end)

    o.newsCenter:subscribeUIBnds()



    for i = 1, 3 do

        o.im.Subscribe("bnd_date" .. i .. "Y", function() o:dateAnim() end)

    end

    o.im.Subscribe("deadlineclock", function() o:publishDeadlineTime() end)

    o.nav.AddActionHandler("killScreen", false, nil, function() o:finalize() end)

    o.im.RegisterAction(PROGRESS, function()

        o:NoMatch(); o:publishDate1(); o:publishDate2(); o:publishDate3()

    end)

    

    if displayMatchdayFixtures then       

        o.nav.Event(nil, "evt_show_overlay", {

            vvm  = "/flows/mainflow/gamemodes/Liga/Screens/MatchResults/MatchResults.vvm",

            data = {nav = o.nav, clbk = function() o.matchSimulator:simulateDayMatches(GLOBAL_DATE_PLACEHOLDER) end}

        })

    end



    glInstancePasser:getInstance(o)

    o.newsCenter:displayNews()

    o:dateAnim()

    o.backgroundProcessor:start()
    
    if sessionVars.get("IntlCallupIncomplete") then

    local msg = [[
Select squad to begin tournament.
Squads lock when confirmed.
Proceed to selection.
]]

    local btn = {"Ok"}

    local clbk = function()
        o.nav.Event(nil, "evt_intlscreen")
    end

    o.FCPopup:getResponse(msg, btn, clbk)

end

    prismLoadMark("hub: built")
    return o

end

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
    if path == "/Save/Save.lua" then
        -- the file to read: the career's slot, or the newest save
        do local PS = rawget(_G, "PrismSlots"); if PS and PS.readPath then local okP, p = pcall(PS.readPath); if okP and p then path = p end end end
        prismRecoverSave(path)
    end
    json.load(function(data)
        if data then
            callback(data)
        else
            callback(nil)
        end
    end, path)
end

local function validateSave(callback, self)
    readJSON("/Save/Save.lua", function(data)

        if data then
            callback(true, self)
        else
            callback(false, self)
        end
    end)
end


function Liga:checkSaveHealth()
  local msg = ""
  validateSave(function(aval, self)
    if aval then msg = "Save is available" else msg = "Save is corrupted, Try saving again before exiting." end
    -- what the career store holds: the generation count and the newest valid one
    local f, st = rawget(_G, "F16_SVC"), ""
    -- the store status of the career's slot
    local slotFile = "Save.lua"
    do local PS = rawget(_G, "PrismSlots"); if PS and PS.active and PS.name then slotFile = PS.name(PS.active) or slotFile end end
    if f and f.Cmd then pcall(function() f.Cmd("store:status|" .. slotFile); st = tostring(f.Out()) end) end
    local n, d = st:match("store: (%d+) generation%(s%), newest valid %d+ %(%d+ bytes, d=([^;]*)")
    if n then msg = msg .. "\n" .. n .. " verified backup" .. (n == "1" and "" or "s") .. " (newest " .. d .. ")" end
    self.FCPopup:getResponse(msg, {"Ok"}, function() end)
  end, self)
end
-- ── Sim Mode Toggle ────────────────────────────────────────────────────────



function Liga:toggleSim(data)

    if data ~= "init" then self.simMode = not self.simMode end

    self.im.Publish("simmode", "Sim Mode: " .. (self.simMode and "ON" or "OFF"))

end



-- ── News Display ───────────────────────────────────────────────────────────

-- Converted to BP animation track "newsAnim".

-- Identical timing and phase logic to the original; no external Timer used.



function Liga:displayNewsInline(dir, callback)

    -- The news card is open in its expanded/comments view - don't let the
    -- background cycle move or swap it out from under the user.
    if self.newsCenter and self.newsCenter.newsExpanded then
        if callback then callback() end
        return
    end

    dir = dir or 1

    -- Cancel any in-progress news animation; the new one takes over.

    self.backgroundProcessor:removeAnimTrack("newsAnim")

    self.isNewsAnimating = true



    local phaseDuration  = 0.15

    local stepInterval   = 0.016

    local stepsPerPhase  = math.max(1, math.floor(phaseDuration / stepInterval))

    local totalSteps     = stepsPerPhase * 2



    local phase1StartPos  = 20

    local phase1TargetPos = dir == 1 and -80 or 120

    local phase2StartPos  = dir == 1 and 120 or -80

    local phase2TargetPos = 20



    local step = 0

    local bp   = self.backgroundProcessor



    bp:registerAnimTrack("newsAnim", function()

        -- Cancellation check: external code sets isNewsAnimating=false to abort.

        if not self.isNewsAnimating then

            bp:removeAnimTrack("newsAnim")

            if callback then callback() end

            return

        end



        step = step + 1



        if step > totalSteps then

            bp:removeAnimTrack("newsAnim")

            self.isNewsAnimating = false

            self.im.Publish("news_position", phase2TargetPos)

            self.im.Publish("news_alpha", 1)

            if callback then callback() end

            return

        end



        local isPhase1  = step <= stepsPerPhase

        local phaseStep = isPhase1 and step or (step - stepsPerPhase)

        local t         = phaseStep / stepsPerPhase

        local easedT    = 1 - (1 - t) * (1 - t)



        if isPhase1 then

            local pos   = phase1StartPos + (phase1TargetPos - phase1StartPos) * easedT

            local alpha = 1 - easedT

            self.im.Publish("news_position", math.floor(pos + 0.5))

            self.im.Publish("news_alpha",    math.floor(alpha * 100 + 0.5) / 100)

        else

            if phaseStep == 1 then

                self.newsCenter:displayNews()

                self.im.Publish("news_position", phase2StartPos)

                self.im.Publish("news_alpha", 1)

            end

            local pos = phase2StartPos + (phase2TargetPos - phase2StartPos) * easedT

            self.im.Publish("news_position", math.floor(pos + 0.5))

            self.im.Publish("news_alpha", 1)

        end

    end, stepInterval)

end



-- ── Team Form Cache ────────────────────────────────────────────────────────



function updateTeamFormCache(self)

    local batchSize = 10

    local matches   = sessionVars.get("MatchData") or {}

    if not GLOBAL_MATCHUP_COUNT or GLOBAL_MATCHUP_COUNT < 5 then return end

    TeamFormCache = {}

    for i = 1, #TeamList, batchSize do

        for j = i, math.min(i + batchSize - 1, #TeamList) do

            local teamID = TeamList[j]

            TeamFormCache[teamID] = { wins=0, draws=0, losses=0 }

        end

    end

    local matchesPerDay   = math.floor(#TeamList / 2)

    local currentMatchday = GLOBAL_MATCHUP_COUNT + 1

    local startMatchday   = math.max(1, currentMatchday - 5)

    local startIndex      = (startMatchday - 1) * matchesPerDay + 1

    local endIndex        = math.min((currentMatchday - 1) * matchesPerDay, #matches)

    for i = startIndex, endIndex, batchSize do

        for j = i, math.min(i + batchSize - 1, endIndex) do

            local match = matches[j]

            if match and (match.matchType == "League"

            or             match.matchType == "Competition") then

                local hID = match.homeID; local aID = match.awayID

                local hs  = match.homeScore or 0; local as = match.awayScore or 0

                if TeamFormCache[hID] then

                    if     hs > as  then TeamFormCache[hID].wins   = TeamFormCache[hID].wins   + 1

                    elseif hs == as then TeamFormCache[hID].draws  = TeamFormCache[hID].draws  + 1

                    else                 TeamFormCache[hID].losses = TeamFormCache[hID].losses + 1

                    end

                end

                if TeamFormCache[aID] then

                    if     as > hs  then TeamFormCache[aID].wins   = TeamFormCache[aID].wins   + 1

                    elseif hs == as then TeamFormCache[aID].draws  = TeamFormCache[aID].draws  + 1

                    else                 TeamFormCache[aID].losses = TeamFormCache[aID].losses + 1

                    end

                end

            end

        end

    end

end



function NewsCenter:refreshNewsCache()

    self.newsCenter:displayNews()

end



function AITransfers:processPendingTransfers()

    local batchSize = 10

    local transfers = self:getPendingTransfers() or {}

    for i = 1, #transfers, batchSize do

        for j = i, math.min(i + batchSize - 1, #transfers) do end

    end

end



-- ── Interval Task Handlers ─────────────────────────────────────────────────



function Liga:processTransfersTask()
    if sessionVars.get("InLeagueMode") then return end
    if (function() local PSU = rawget(_G, "PrismSetup"); return PSU and PSU.marketMul and PSU.marketMul() or 1 end)() <= 0 then return end   -- the career setup switched the AI market off

    if not Date:IsTransferWindowOpen() then return end

    self.models.AITransfers:batchTransfers()

end



function Liga:processScoutingTask()
    if sessionVars.get("InLeagueMode") then return end

    self.models.AITransfers:batchScouting()

end



-- ── User Interaction ───────────────────────────────────────────────────────



function Liga:onUserInteraction()

    self.lastInteractionTime = os.clock()

    self.backgroundProcessor:pause()

end



-- ── UI Helpers ─────────────────────────────────────────────────────────────



function Liga:clearUI()

    for i = 1, #UIbnds do self.im.Publish(UIbnds[i], "") end

end



function Liga:dateAnim()

    if isDeadlineActive() then

        self.isAnimating = false

        self.im.Publish(BND_IS_DATE_SIM,     false)

        self.im.Publish(BND_IS_NOT_DATE_SIM, true)

        return

    end

    for i = 1, 3 do

        self.im.Publish("bnd_date" .. i .. "Y", self.dateYPositions[i])

    end

    self.im.Publish("dateTS1",          20)

    self.im.Publish("dateTS2",          40)

    self.im.Publish(BND_IS_DATE_SIM,     self.isAnimating)

    self.im.Publish(BND_IS_NOT_DATE_SIM, not self.isAnimating)

end



function Liga:testScript()

    self.nav.Event(nil, "evt_back")

end



function Liga:_handleTransfer(player, team)

    self.transferSystem:replaceSoldPlayer(player, team, self.squads, self.services)

end



function Liga:publishBg()

    self.im.Publish("bnd_epl_visible", self.eplvisible)

end



function Liga:isDateReached(currentDate, recoveryDate)

    return self.DateUtils:isDateReached(currentDate, recoveryDate)

end



local function safeTableConcat(tbl)

    local result = {}

    for i, v in ipairs(tbl) do result[i] = tostring(v) end

    return table.concat(result, ", ")

end



function Liga:publishDeadlineTime()

    local hours   = math.floor(self.deadlineTime / 60)

    self.im.Publish("bnd_isdeadline",   isDeadlineActive())

    self.im.Publish("deadlineclock",    "$clock" .. ((10 - hours) + 1))

    self.im.Publish("bnd_deadlinetime", string.format("%02d:%02d", hours, 0))

    self.im.Publish("bnd_deadlinecolor",formatDeadlineColor(self.deadlineTime))

end



local function formatPositionText(spacecount, textcount)

    local x = 105

    x = x + ((textcount - spacecount) * 26)

    x = x + (spacecount * 2)

    return x

end



-- ── Finish Label Publisher ─────────────────────────────────────────────────

-- League Mode is a single-season competition. As soon as every fixture in the
-- selected league has been played (or the calendar reaches season end as a
-- safety net), freeze the final table position and switch the hub into the same
-- result/exit state used by standalone tournaments.
function Liga:syncLeagueCompletion(forceEnd)
    if not sessionVars.get("InLeagueMode") then return false end
    if sessionVars.get("EndLeague") then return true end

    local leagueID = sessionVars.get("currentUserLeagueID")
    local teamID   = sessionVars.get("currentSelectedTeamID") or currentSelectedTeamID
    if not leagueID or not teamID then return false end

    local leagueMatches = (sessionVars.get("LeagueMatchData") or {})[leagueID] or {}
    local sawLeagueMatch = false

    if not forceEnd then
        for i = 1, #leagueMatches do
            local m = leagueMatches[i]
            if m and (m.matchType == nil or m.matchType == "League") then
                sawLeagueMatch = true
                if not m.played then return false end
            end
        end
        if not sawLeagueMatch then return false end
    end

    local position = self.TeamStats:getTeamPosition(leagueID, teamID)
    if not position or position < 1 then return false end

    sessionVars.set("UserLeaguePosition", position)
    sessionVars.set("EndLeague", true)
    return true
end

function Liga:publishFinishLabel()
    if (rawget(_G, "PRISM_TRACE_FRAMES") or 0) > 0 then do local c = rawget(_G, "PRISM_CRUMB"); if c then c("hub: publishFinishLabel") end end end

    local inTourneyMode   = sessionVars.get("InTourneyMode")

    local tourneyLeagueID = inTourneyMode and sessionVars.get("currentUserLeagueID")

    local userLeagueID    = sessionVars.get("currentUserLeagueID")

    local dateString      = GLOBAL_DATE_PLACEHOLDER or "01/08/25"
    local leagueEnded     = self:syncLeagueCompletion(Date:isSeasonEnd())



    local function resetCrests()

        self.im.Publish("crestsizeW",  55); self.im.Publish("crestsizeH",  55)

        self.im.Publish("cresthomeX", -230); self.im.Publish("crestawayX", -160)

        self.im.Publish("crestalpha",   1)

    end


    if displayMatchdayFixtures then
        self.im.Publish("bnd_date_label",     ""); self.im.Publish("bnd_month_label",    "")
        self.im.Publish("bnd_matchup_label",  ""); self.im.Publish("bnd_matchdate_label","")
        self.im.Publish("bnd_league_label",   ""); self.im.Publish("bnd_matchtag",       "")
        self.im.Publish("bnd_home_name",      ""); self.im.Publish("bnd_away_name",      "")
        self.im.Publish("bnd_homeRank",       ""); self.im.Publish("bnd_awayRank",       "")
        self.im.Publish("bnd_homeRankX",      ""); self.im.Publish("bnd_awayRankX",      "")
        self.im.Publish("bnd_advance_label",  "")
        self.im.Publish("bnd_home_crest",     ""); self.im.Publish("bnd_away_crest",     "")
        self.im.Publish("matchleague",        "")
        resetCrests(); return
    end

    if not dateString then

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", "No date available")

        self.im.Publish("bnd_homeRank",  ""); self.im.Publish("bnd_awayRank",  "")

        self.im.Publish("bnd_homeRankX", ""); self.im.Publish("bnd_awayRankX", "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_league_label",""); self.im.Publish("bnd_matchdate_label","")

        resetCrests(); return

    end



    local currentDay, currentMonth, currentYear =

        dateString:match("^(%d%d)/(%d%d)/(%d%d)$")

    currentDay   = tonumber(currentDay)

    currentMonth = tonumber(currentMonth)

    currentYear  = tonumber(currentYear)



    if not currentDay then

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", "Invalid date")

        self.im.Publish("bnd_homeRank",  ""); self.im.Publish("bnd_awayRank",  "")

        self.im.Publish("bnd_homeRankX", ""); self.im.Publish("bnd_awayRankX", "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_league_label",""); self.im.Publish("bnd_matchdate_label","")

        resetCrests(); return

    end



    if leagueEnded then

        local finalPosition = sessionVars.get("UserLeaguePosition") or
            self.TeamStats:getTeamPosition(userLeagueID, currentSelectedTeamID) or 0

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")
        self.im.Publish("bnd_matchup_label", "Season Results")
        self.im.Publish("bnd_matchdate_label", "Final Position")
        self.im.Publish("bnd_league_label",  "")
        self.im.Publish("bnd_matchtag",      "")
        self.im.Publish("bnd_home_crest",    {name="$LeagueLogo", id=userLeagueID})
        self.im.Publish("bnd_away_crest",    {name="$Crest", id=currentSelectedTeamID})
        self.im.Publish("matchleague",       {})
        self.im.Publish("bnd_home_name",     LeagueNames[userLeagueID] or "League")
        self.im.Publish("bnd_away_name",     finalPosition > 0 and ordinal(finalPosition) or "-")
        self.im.Publish("bnd_homeRank",      ""); self.im.Publish("bnd_awayRank",      "")
        self.im.Publish("bnd_homeRankX",     ""); self.im.Publish("bnd_awayRankX",     "")
        resetCrests()
        self.im.Publish("bnd_advance_label", "End League"); return

    elseif Date:isSeasonEnd() then

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", "Season Ended")

        self.im.Publish("bnd_matchdate_label",""); self.im.Publish("bnd_league_label",  "")

        self.im.Publish("bnd_matchtag",      "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

        self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

        resetCrests()

        self.im.Publish("bnd_advance_label", "Start New Season"); return

    elseif isDeadlineActive() then

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", "")

        self.im.Publish("bnd_matchdate_label","Time remaining")

        self.im.Publish("bnd_league_label",  ""); self.im.Publish("bnd_matchtag",      "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

        self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

        resetCrests()

        self.im.Publish("bnd_advance_label",

            self.deadlineTime <= 0 and "Deadline Passed"

            or (self.isAnimating and "Advancing..." or "Advance One Hour")); return

    elseif inTourneyMode and sessionVars.get("EndTourney") then

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", "Season Results")

        self.im.Publish("bnd_matchdate_label",""); self.im.Publish("bnd_league_label",  "")

        self.im.Publish("bnd_matchtag",      "")

        self.im.Publish("bnd_home_crest",  {name="$LeagueLogo", id=userLeagueID})

        self.im.Publish("bnd_away_crest",  {name="$Crest", id=currentSelectedTeamID})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   LeagueNames[userLeagueID])

        self.im.Publish("bnd_away_name", sessionVars.get("UserTournamentStatus"))

        self.im.Publish("bnd_homeRank",  ""); self.im.Publish("bnd_awayRank",  "")

        self.im.Publish("bnd_homeRankX", ""); self.im.Publish("bnd_awayRankX", "")

        resetCrests()

        self.im.Publish("bnd_advance_label", "End Tournament"); return

    end



    local homeID, awayID, matchIndex =

        findCurrentDayMatch(self, dateString, currentSelectedTeamID)

    matchday = homeID ~= nil

    local daysToFixture, matchDateStr, nextHomeID, nextAwayID,

          nextLeagueID, nextMatchType, round, errorMsg =

        daysToNextMatch(self, dateString, currentSelectedTeamID)

    local currentMonthName = self.DateUtils.MONTH_NAMES_FULL[currentMonth] or "Unknown"



    if matchday then

        self.im.Publish("bnd_date_label",  ""); self.im.Publish("bnd_month_label", "")

        local matches       = sessionVars.get("MatchData") or {}

        local selectedMatch = matchIndex and matches[matchIndex]
        
        local isRound = selectedMatch and selectedMatch.matchRound

        local effectiveLeagueID = selectedMatch and selectedMatch.leagueID
                       or tourneyLeagueID
                       or getTeamLeague(currentSelectedTeamID)
                       or sessionVars.get("currentUserLeagueID") or 13

        if effectiveLeagueID and effectiveLeagueID ~= 0 then

            sessionVars.set("currentUserLeagueID", effectiveLeagueID)

        end

        if not selectedMatch then

            self.im.Publish("bnd_matchup_label","No match scheduled today")

            self.im.Publish("bnd_matchdate_label",""); self.im.Publish("bnd_league_label","")

            self.im.Publish("bnd_matchtag",      "")

            self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

            self.im.Publish("matchleague",     {})

            self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

            self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

            self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

            resetCrests()

        else

            local homeName = selectedMatch.homeID

                and self.loc and self.loc.LocalizeString("TeamName_Abbr15_"..selectedMatch.homeID) or ""

            local awayName = selectedMatch.awayID

                and self.loc and self.loc.LocalizeString("TeamName_Abbr15_"..selectedMatch.awayID) or ""

            local len1, len2 = #homeName, #awayName

            local sp1 = select(2, homeName:gsub("%s",""))

            local sp2 = select(2, awayName:gsub("%s",""))

            local homerank = self.TeamStats:getTeamPosition(effectiveLeagueID, nextHomeID)

            local awayrank = self.TeamStats:getTeamPosition(effectiveLeagueID, nextAwayID)

            self.im.Publish("bnd_homeRank",  ordinal(homerank))

            self.im.Publish("bnd_awayRank",  ordinal(awayrank))

            self.im.Publish("bnd_homeRankX", formatPositionText(sp1, len1))

            self.im.Publish("bnd_awayRankX", formatPositionText(sp2, len2))

            local mds = self.DateUtils:convertMatchDateToStandard(selectedMatch.date)
            
            if isRound then

            publishMatchDetails(self, 0, mds, selectedMatch.homeID, selectedMatch.awayID,

                homeName, awayName, selectedMatch.matchType, effectiveLeagueID, selectedMatch.matchRound)
           else
             publishMatchDetails(self, 0, mds, selectedMatch.homeID, selectedMatch.awayID,

                homeName, awayName, selectedMatch.matchType, effectiveLeagueID)
            end

        end

    else

        local effectiveNextLeagueID = tourneyLeagueID or nextLeagueID

            or getTeamLeague(currentSelectedTeamID)

            or sessionVars.get("currentUserLeagueID") or 13

        if effectiveNextLeagueID and effectiveNextLeagueID ~= 0 then

            sessionVars.set("currentUserLeagueID", effectiveNextLeagueID)

        end

        self.im.Publish("bnd_date_label",  currentDay)

        self.im.Publish("bnd_month_label", currentMonthName)



        if daysToFixture and daysToFixture <= 7 then

            local homeName = nextHomeID

                and self.loc and self.loc.LocalizeString("TeamName_Abbr15_"..nextHomeID) or ""

            local awayName = nextAwayID

                and self.loc and self.loc.LocalizeString("TeamName_Abbr15_"..nextAwayID) or ""

            local len1, len2 = #homeName, #awayName

            local sp1 = select(2, homeName:gsub("%s",""))

            local sp2 = select(2, awayName:gsub("%s",""))

            local homerank = self.TeamStats:getTeamPosition(effectiveNextLeagueID, nextHomeID)

            local awayrank = self.TeamStats:getTeamPosition(effectiveNextLeagueID, nextAwayID)

            self.im.Publish("bnd_homeRank",  ordinal(homerank))

            self.im.Publish("bnd_awayRank",  ordinal(awayrank))

            self.im.Publish("bnd_homeRankX", formatPositionText(sp1, len1))

            self.im.Publish("bnd_awayRankX", formatPositionText(sp2, len2))

            publishMatchDetails(self, daysToFixture, matchDateStr, nextHomeID, nextAwayID,

                homeName, awayName, nextMatchType, effectiveNextLeagueID, round)

        else

            local safeLeague = tourneyLeagueID

                or getTeamLeague(currentSelectedTeamID)

                or sessionVars.get("currentUserLeagueID") or 13

            if safeLeague and safeLeague ~= 0 then

                sessionVars.set("currentUserLeagueID", safeLeague)

            end

            self.im.Publish("bnd_matchup_label",  errorMsg or "No upcoming matches")

            self.im.Publish("bnd_matchdate_label", ""); self.im.Publish("bnd_league_label",    "")

            self.im.Publish("bnd_matchtag",        "")

            self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

            self.im.Publish("matchleague",     {})

            self.im.Publish("bnd_home_name",   non or ""); self.im.Publish("bnd_away_name",   "")

            self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

            self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

            resetCrests()

        end



        self.isMatchdayAnimating = false

        self.backgroundProcessor:removeAnimTrack("matchdayAnim")

    end



    if not Date:isSeasonEnd() and not isDeadlineActive() then

        self.im.Publish("bnd_advance_label",

            self.isAutoAdvancing and "Stop simulation"

            or (matchday and "Matchday" or "Advance"))

    end

    -- Task rows are visual alerts, not date-specific content. Keep them
    -- visible whenever they contain tasks; matchdayAnim owns the only
    -- temporary hide state and restores it when the animation completes.
    if self.UItasks and not self.isMatchdayAnimating then

        self.UItasks:_rowDisplay("show")

    end

end



-- ── Play Match ─────────────────────────────────────────────────────────────



local function previousLegScores(matches, current)
    if not current.tieId or current.leg ~= 2 then return 0, 0 end
    for _, m in ipairs(matches) do
        if m.tieId == current.tieId and m.leg == 1 and m.played then
            local previousHome = m.homeID == current.homeID and m.homeScore or m.awayScore
            local previousAway = m.homeID == current.awayID and m.homeScore or m.awayScore
            return previousHome or 0, previousAway or 0
        end
    end
    return 0, 0
end

local function byteHex(value)
    value = math.floor(tonumber(value) or 0)
    if value < 0 then value = 0 elseif value > 255 then value = 255 end
    return string.format("%02X", value)
end

function Liga:sendMatchConfig(matchData, matches)
    local previousHome, previousAway = previousLegScores(matches, matchData)
    -- Lua cannot mutate the engine fixture. The native libfifa hook consumes
    -- these as the authoritative previous-leg scores before kickoff.
    currentMatch.InitialHomeScore = previousHome
    currentMatch.InitialAwayScore = previousAway
    local mask = matchData.endRuleMask
    if mask == nil then mask = matchData.isKnockout and 0x28 or 0x01 end
    local url = "matchcfg://" .. byteHex(previousHome)
        .. byteHex(previousAway) .. byteHex(mask)
    -- The matchcfg:// browser call is gone: the APK's FileBridge.recordMatchConfig is an empty method and no
    -- native code reads it. The previous-leg scores travel in currentMatch.InitialHome/AwayScore.
    sessionVars.set("LastMatchConfig", {
        url=url, previousHome=previousHome, previousAway=previousAway,
        initialHomeScore=previousHome, initialAwayScore=previousAway,
        endRuleMask=mask, tieId=matchData.tieId, leg=matchData.leg,
    })
end

function Liga:PlayMatch()

    local currentDate = GLOBAL_DATE_PLACEHOLDER or "01/08/25"

    local homeID, awayID, matchIndex =

        findCurrentDayMatch(self, currentDate, currentSelectedTeamID)

    if not homeID then

        self.im.Publish("bnd_matchup_label", "No match scheduled today"); return

    end

    local matches          = sessionVars.get("MatchData") or {}

    local currentMatchData = matches[matchIndex]

    currentLigaData = currentLigaData or {}

    currentLigaData.Index   = ligaId; currentLigaData.round   = matchIndex

    currentLigaData.homeID  = currentMatchData.homeID; currentLigaData.awayID  = currentMatchData.awayID

    currentLigaData.leagueID= currentMatchData.leagueID
    -- The cards of an earlier try at this match (End Match) do not stand.
    do local S = rawget(_G, "PRISM_SUSP"); if S and S.discardPending then pcall(S.discardPending) end end

    currentLigaData.difficulty = currentMatchData.difficulty or 1

    currentMatch.MatchType  = currentMatchData.matchType

    currentMatch.HomeTeamID = currentMatchData.homeID; currentMatch.AwayTeamID = currentMatchData.awayID
    -- Development in real matches: the two clubs' developed attributes go into the engine's
    -- override table.
    do local CD = rawget(_G, "CareerDev"); if CD and CD.syncMatchOverrides and currentMatch then pcall(CD.syncMatchOverrides, { currentMatch.HomeTeamID, currentMatch.AwayTeamID }, "hub") end end

    currentMatch.isKnockout = currentMatchData.isKnockout or false

    local allowExtraTime = currentMatchData.allowExtraTime
    if allowExtraTime == nil then allowExtraTime = currentMatchData.isKnockout or false end
    currentMatch.allowExtraTime = allowExtraTime
    self:sendMatchConfig(currentMatchData, matches)

    -- Safety net: if this screen was reached without going through NoMatch's
    -- date-swipe animation (e.g. evt_reload straight onto a matchday), make
    -- sure the AI manager has picked today's squad. pickAISquad no-ops if it
    -- already picked for this date/team, so this never reshuffles a squad
    -- the user has already seen.
    if sessionVars.get("InPlayerCareerMode") and self.playerCareer then
        local opponentID = (homeID == currentSelectedTeamID) and awayID or homeID
        self.playerCareer:pickAISquad(currentSelectedTeamID, opponentID)
    end

    local players      = getCachedTeamPlayers(currentSelectedTeamID)

    local lgId = sessionVars.get("currentUserLeagueID")

    local squadSize    = #players

    -- Unavailable = banned from THIS match's competition, or injured (the HUD files an injury under
    -- the user's league).
    local function prismUnavailable(id, lg, md)
        local S = rawget(_G, "PRISM_SUSP")
        if S and S.unavailable then
            local ok, v = pcall(S.unavailable, id, md and md.leagueID or lg)
            if ok then return v end
        end
        return isSuspended and isSuspended[lg] and (isSuspended[lg][id] == 1 or isSuspended[lg][id] == 2)
    end
    local ineligible   = false

    local ineligibleCount = 0

    

    for i = 1, squadSize do

        local id = players[i].CARD_ID

        if prismUnavailable(id, lgId, currentMatchData)
then

    ineligibleCount = ineligibleCount + 1



    if i <= 16 then

        ineligible = true

    end

end

    end

    if ineligible then

        local count = ineligibleCount + 16

        if count > squadSize then ineligible = false end

    end

    -- Player Career gate: the user can only PLAY the match if their

    -- controlled player is in the AI manager's starting XI. If benched,

    -- the match is sim-only (the user watches the result).

    if sessionVars.get("InPlayerCareerMode") and self.playerCareer then
        if not self.playerCareer:canPlayMatch() then
          self.nav.Event(nil, "evt_show_overlay", {vvm = "/flows/mainflow/gamemodes/Liga/Screens/MatchSimulation/MatchSim.vvm", data = {advance = function() self.nav.Event(nil, "evt_reload") self.nav.Event(nil, "evt_hide_overlay") end}})       
          return    
        end
    end

    -- who stopped the match, and why (R98e, NewClub.patch.js)
    if ineligible then
        local S, why = rawget(_G, "PRISM_SUSP"), {}
        for i = 1, math.min(16, squadSize) do
            local p = players[i]
            if p and prismUnavailable(p.CARD_ID, lgId, currentMatchData) then
                local inj = S and S.isInjured and S.isInjured(p.CARD_ID)
                why[#why + 1] = tostring(p.playerName or p.name or p.CARD_ID) .. " (#" .. i .. ", " .. (inj and "injured" or "banned") .. ")"
            end
        end
        local f = rawget(_G, "F16_SVC"); if f and f.Cmd then pcall(f.Cmd, "log:career: ineligible in the matchday 16 of " .. tostring(currentSelectedTeamID) .. " (competition " .. tostring(currentMatchData and currentMatchData.leagueID) .. "): " .. table.concat(why, ", ")) end
    end
    if ineligible then self:Ineligible() else self:KickOff(allowExtraTime) end

end



-- ── Deadline Animation ─────────────────────────────────────────────────────

-- Converted to BP animation track "deadlineAnim".

-- stepInterval: 0.083 s (12 fps countdown for 60 seconds = 5 seconds wall time).

-- The track fires at its own interval independently of other tracks.



function Liga:animateDeadlineTimeInline(callback)

    self.backgroundProcessor:removeAnimTrack("deadlineAnim")

    self.isAnimating = true

    self.im.Publish("bnd_showAdvanceBtn", false)

    self.im.Publish("bnd_isNotDateSim",   false)



    local stepInterval  = 0.04

    local totalSteps    = 60

    local currentHours  = math.floor(self.deadlineTime / 60)



    local function setDeadlineUI()

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", ""); self.im.Publish("bnd_matchdate_label","Time remaining")

        self.im.Publish("bnd_league_label",  ""); self.im.Publish("bnd_matchtag",      "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

        self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

        self.im.Publish("crestsizeW",  55); self.im.Publish("crestsizeH",  55)

        self.im.Publish("cresthomeX", -230); self.im.Publish("crestawayX", -160)

        self.im.Publish("crestalpha",   1)

    end



    -- Pre-animation setup (equivalent to the original onTimerComplete at step 0)

    if self.deadlineTime % 60 == 0 then

        currentHours = currentHours - 1

        if currentHours < 0 then

            -- Immediate completion (deadline already at 0)

            self.deadlineTime = 0

            self.im.Publish("bnd_advance_label",  "Deadline Passed")

            self.im.Publish("bnd_isdeadline",     false)

            self.im.Publish("bnd_deadlinetime",   "00:00")

            self.im.Publish("bnd_deadlinecolor",  "0xFF0D00")

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            setDeadlineUI()

            self.Date:advanceDate()

            self.deadlineTime = 10 * 60

            self:publishFinishLabel()

            self.isAnimating = false

            if callback then callback(true) end

            return

        end

        self.deadlineTime = currentHours * 60 + 59

    else

        self.deadlineTime = currentHours * 60 + 59

    end

    self:publishDeadlineTime(); setDeadlineUI()



    local step = 0

    local bp   = self.backgroundProcessor



    bp:registerAnimTrack("deadlineAnim", function()

        -- Cancellation check

        if not self.isAnimating then

            bp:removeAnimTrack("deadlineAnim")

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            self:publishDeadlineTime(); setDeadlineUI()

            self.im.Publish("bnd_advance_label",

                self.deadlineTime <= 0 and "Deadline Passed" or "Advance One Hour")

            if callback then callback(false) end

            return

        end



        step = step + 1



        if step > totalSteps then

            bp:removeAnimTrack("deadlineAnim")

            self.deadlineTime = currentHours * 60

            self:publishDeadlineTime(); setDeadlineUI()

            if currentHours <= 0 then

                self.deadlineTime = 0

                self.im.Publish("bnd_advance_label",  "Deadline Passed")

                self.im.Publish("bnd_isdeadline",     false)

                self.im.Publish("bnd_deadlinetime",   "00:00")

                self.im.Publish("bnd_deadlinecolor",  "0xFF0D00")

                self.im.Publish("bnd_showAdvanceBtn", true)

                self.im.Publish("bnd_isNotDateSim",   true)

                sessionVars.set("deadlineTime", nil)

                self.deadlineTime = 10 * 60

                -- Diagnostics: crumbs along the deadline -> new-day path, then a few hub frames.
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: the last hour ran out, advancing the date") end end
                self.Date:advanceDate()
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: date advanced to " .. tostring(GLOBAL_DATE_PLACEHOLDER) .. ", finish label next") end end
                self:publishFinishLabel()
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: finish label published") end end
                self.isAnimating = false
                if callback then callback(true) end
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: callback done; tracing the next hub frames") end end
                rawset(_G, "PRISM_TRACE_FRAMES", 8)

                return

            end

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            self.im.Publish("bnd_advance_label",  "Advance One Hour")

            sessionVars.set("deadlineTime", self.deadlineTime)

            self.isAnimating = false

            if callback then callback(false) end

            return

        end



        local currentMinutes = 59 - (step - 1)

        self.im.Publish("bnd_deadlinetime",

            string.format("%02d:%02d", currentHours, currentMinutes))

        self.im.Publish("bnd_deadlinecolor",

            formatDeadlineColor(currentHours * 60 + currentMinutes))

        setDeadlineUI()

    end, stepInterval)

end



-- ── Date Swipe Animation ───────────────────────────────────────────────────

-- Converted to BP animation track "dateSwipe".

-- Runs at 0.016 s/step (≈60 fps).  Two phases share the same step counter.



function Liga:animateDateSwipeInline(callback)

    self.backgroundProcessor:removeAnimTrack("dateSwipe")

    self.isAnimating = true

    -- No setAnimating(true, true): animation IS a BP track; pausing BP kills it.



    self.dateYPositions = {-100, -50, 0}

    self.im.Publish("bnd_date1Y", self.dateYPositions[1])

    self.im.Publish("bnd_date2Y", self.dateYPositions[2])

    self.im.Publish("bnd_date3Y", self.dateYPositions[3])

    self.im.Publish("bnd_dateAA3", 1)

    self.im.Publish("dateTS1", 20); self.im.Publish("dateTS2", 40)

    self:dateAnim()



    local totalDuration  = 0.3

    local phaseDuration  = 0.15

    local stepInterval   = 0.016

    local totalSteps     = math.max(1, math.floor(totalDuration  / stepInterval))

    local stepsPerPhase  = math.max(1, math.floor(phaseDuration  / stepInterval))



    local startY12  = {-100, -50}

    local targetY12 = {-50,    0}

    local startTS1, targetTS1  =  20,  40

    local startTS2, targetTS2  =  40,  20

    local p1StartY3, p1TargetY3, p1StartA, p1TargetA =    0, 30, 1, 0

    local p2StartY3, p2TargetY3, p2StartA, p2TargetA = -130, -100, 0, 1



    local step                   = 0

    local hasAdvancedDate        = false

    local pendingMatchdayAnim    = false

    local bp                     = self.backgroundProcessor



    bp:registerAnimTrack("dateSwipe", function()

        -- Cancellation check

        if not self.isAnimating then

            bp:removeAnimTrack("dateSwipe")

            self:dateAnim()

            if callback then callback() end

            return

        end



        step = step + 1



        if step > totalSteps then

            bp:removeAnimTrack("dateSwipe")

            self.isAnimating = false

            self.dateYPositions = {-100, -50, 0}

            for i = 1, 3 do self.im.Publish("bnd_date"..i.."Y", self.dateYPositions[i]) end

            self.im.Publish("bnd_dateAA3", p2TargetA)

            self.im.Publish("dateTS1", 20); self.im.Publish("dateTS2", 40)

            self:publishDate1(); self:publishDate2(); self:publishDate3()

            self:publishFinishLabel()

            if pendingMatchdayAnim then

                self:matchdayAnim(function()

                    self.isAnimating = false

                    self:dateAnim(); self:publishFinishLabel()

                    if callback then callback() end

                end, function() end)

            else

                self.isAnimating = false

                self:dateAnim(); self:publishFinishLabel()

                if callback then callback() end

            end

            return

        end



        local t        = step / totalSteps

        local easedT   = 1 - (1 - t) * (1 - t)

        local isPhase1 = step <= stepsPerPhase

        local phaseStep= isPhase1 and step or (step - stepsPerPhase)

        local phaseT   = phaseStep / stepsPerPhase

        local ePT      = 1 - (1 - phaseT) * (1 - phaseT)



        local cY12 = {

            startY12[1] + (targetY12[1] - startY12[1]) * easedT,

            startY12[2] + (targetY12[2] - startY12[2]) * easedT,

        }

        local cTS1 = startTS1 + (targetTS1 - startTS1) * easedT

        local cTS2 = startTS2 + (targetTS2 - startTS2) * easedT

        self.im.Publish("bnd_date1Y", math.floor(cY12[1]+0.5))

        self.im.Publish("bnd_date2Y", math.floor(cY12[2]+0.5))

        self.im.Publish("dateTS1",    math.floor(cTS1+0.5))

        self.im.Publish("dateTS2",    math.floor(cTS2+0.5))



        if isPhase1 then

            local cY3 = p1StartY3 + (p1TargetY3 - p1StartY3) * ePT

            local cA  = p1StartA  + (p1TargetA  - p1StartA)  * ePT

            self.im.Publish("bnd_date3Y",  math.floor(cY3+0.5))

            self.im.Publish("bnd_dateAA3", math.floor(cA*100+0.5)/100)

        else

            if phaseStep == 1 and not hasAdvancedDate then

                self.Date:advanceDate(); hasAdvancedDate = true

                local nextDate = self.DateUtils:getNextDay(GLOBAL_DATE_PLACEHOLDER)

                self.im.Publish(BND_DATE3, self.DateUtils:formatDateAsDayName(nextDate))

                local hID, aID = findCurrentDayMatch(self, GLOBAL_DATE_PLACEHOLDER,

                                                currentSelectedTeamID)

                matchday = hID ~= nil

                if matchday then

                    pendingMatchdayAnim = true

                    -- AI manager picks today's matchday squad right here, mid-swipe,
                    -- well before the date-advancement animation finishes, so that
                    -- PlayerCareer:canPlayMatch() / getPlayerSquadStatus() (and
                    -- anything else PlayerCareer exposes) reflect today's selection
                    -- as soon as the animation completes.
                    if sessionVars.get("InPlayerCareerMode") and self.playerCareer then
                        local opponentID = (hID == currentSelectedTeamID) and aID or hID
                        self.playerCareer:pickAISquad(currentSelectedTeamID, opponentID)
                    end                   
                end

                self.im.Publish("bnd_date3Y",  p2StartY3)

                self.im.Publish("bnd_dateAA3", p2StartA)

            end

            local cY3 = p2StartY3 + (p2TargetY3 - p2StartY3) * ePT

            local cA  = p2StartA  + (p2TargetA  - p2StartA)  * ePT

            self.im.Publish("bnd_date3Y",  math.floor(cY3+0.5))

            self.im.Publish("bnd_dateAA3", math.floor(cA*100+0.5)/100)

        end

    end, stepInterval)

end



-- ── Tab Button Animation ───────────────────────────────────────────────────

-- Converted to BP animation track "btnAnim".

-- Uses per-animation interval (fadeOut: 0.033, fadeIn: 0.016) so the

-- countdown rate matches the original without a dynamic timer swap.

-- Inter-button delay (buttonDelay) is modelled as skipTicks: extra ticks

-- to pass through before starting the next button's steps.



function Liga:animateTabButtonsInline(tabsNum, btnTabsXConfig, direction,

        animationType, startOrTargetX, callback)

    if not tabsNum or not btnTabsXConfig or tabsNum < 1 or not startOrTargetX then

        if callback then callback() end; return

    end

    self.backgroundProcessor:removeAnimTrack("btnAnim")

    self.isBtnAnimating = true



    local trackInterval = animationType == "fadeOut" and 0.033 or 0.016

    local buttonDelay   = animationType == "fadeOut" and 0.01  or 0

    -- Convert buttonDelay to "skip ticks" at the track interval.

    -- e.g. fadeOut: 0.01 / 0.033 ≈ 0.3 → 0 extra ticks (absorbed into interval).

    local skipPerButton = math.max(0, math.floor(buttonDelay / trackInterval))

    local steps         = math.max(1, math.floor(0.05 / trackInterval))



    local buttonOrder = {}

    for i = 1, tabsNum do

        buttonOrder[i] = direction == 1 and i or (tabsNum + 1 - i)

    end



    local step      = 0

    local skipCount = 0

    local totalSteps = tabsNum * steps

    local bp         = self.backgroundProcessor



    bp:registerAnimTrack("btnAnim", function()

        -- Cancellation check

        if not self.isBtnAnimating then

            bp:removeAnimTrack("btnAnim")

            if callback then callback() end

            return

        end



        -- Burn off inter-button delay ticks

        if skipCount > 0 then

            skipCount = skipCount - 1

            return

        end



        step = step + 1



        if step > totalSteps then

            bp:removeAnimTrack("btnAnim")

            self.isBtnAnimating = false

            if callback then callback() end

            return

        end



        local btnIdx  = math.floor((step - 1) / steps) + 1

        local stepInB = (step - 1) % steps + 1

        local bIdx    = buttonOrder[btnIdx]

        local startX  = animationType == "fadeOut" and btnTabsXConfig[bIdx] or startOrTargetX

        local targetX = animationType == "fadeOut" and startOrTargetX or btnTabsXConfig[bIdx]

        local t       = stepInB / steps

        local ePT     = 1 - (1 - t) * (1 - t)

        local currX   = startX + (targetX - startX) * ePT

        self.im.Publish("bnd_btnX"..bIdx, math.floor(currX+0.5))

        if stepInB == steps then

            self.im.Publish("bnd_btnX"..bIdx, targetX)

            skipCount = skipPerButton   -- pause before next button

        end

    end, trackInterval)

end



function Liga:_animateTabButtons(tabsNum, btnTabsXConfig, direction,

        animationType, startOrTargetX, callback)

    self:animateTabButtons(tabsNum, btnTabsXConfig, direction,

        animationType, startOrTargetX, callback)

end



-- ── Swipe Tabs Animation ───────────────────────────────────────────────────

-- Converted to BP animation track "swipeAnim".



function Liga:swipeTabsInline(startX, targetX, callback)

    self.backgroundProcessor:removeAnimTrack("swipeAnim")

    self.isSwipeAnimating = true



    local stepInt  = 0.016

    local duration = 0.09

    local steps    = math.floor(duration / stepInt)

    local stepSize = (targetX - startX) / steps

    local step     = 0

    local bp       = self.backgroundProcessor



    bp:registerAnimTrack("swipeAnim", function()

        -- Cancellation check

        if not self.isSwipeAnimating then

            bp:removeAnimTrack("swipeAnim")

            self.im.Publish("bnd_tabsPosX", targetX)

            if callback then callback() end

            return

        end



        step = step + 1



        if step > steps then

            bp:removeAnimTrack("swipeAnim")

            self.isSwipeAnimating = false

            self.im.Publish("bnd_tabsPosX", targetX)

            if callback then callback() end

            return

        end



        self.im.Publish("bnd_tabsPosX", startX + stepSize * step)

    end, stepInt)

end



function Liga:_swipeTab(startX, targetX, callback)

    self:swipeTabs(startX, targetX, callback)

end



-- ── NoMatch (date advance logic) ───────────────────────────────────────────

-- Resolve the advance button from LIVE state every time it is pressed.
-- `matchday` is intentionally not trusted here: it is a UI cache populated by
-- publishFinishLabel/date animation and can be stale after reloads, simulations,
-- mode transitions, or a same-frame season/deadline boundary.
function Liga:_resolveNoMatchState()
    local state = {
        seasonEnd    = Date:isSeasonEnd(),
        deadline     = isDeadlineActive(),
        leagueEnded  = false,
        tourneyEnded = false,
        matchday     = false,
        homeID       = nil,
        awayID       = nil,
        matchIndex   = nil,
    }

    if sessionVars.get("InLeagueMode") then
        state.leagueEnded = self:syncLeagueCompletion(false)
        if not state.leagueEnded and state.seasonEnd then
            -- Preserve the existing season-end safety net for League Mode.
            state.leagueEnded = self:syncLeagueCompletion(true)
        end
    end

    state.tourneyEnded =
        sessionVars.get("InTourneyMode") == true
        and sessionVars.get("EndTourney") == true

    -- Special terminal/time states have priority over a cached/current fixture,
    -- matching publishFinishLabel's visible state ordering.
    if not state.leagueEnded
    and not state.seasonEnd
    and not state.deadline
    and not state.tourneyEnded then
        state.homeID, state.awayID, state.matchIndex =
            findCurrentDayMatch(self,
                GLOBAL_DATE_PLACEHOLDER or "01/08/25",
                currentSelectedTeamID)
        state.matchday = state.homeID ~= nil
    end

    -- Keep the legacy global synchronized for the rest of MatchSelect, but only
    -- after recomputing it from current MatchData/current date.
    matchday = state.matchday
    return state
end


--- Leaves 4 June once the season has turned over. The pre-season league plays its fourth matchday on that day: the
-- user's club plays it first (the date stays; the caller simulates the other clubs' matches), or, with Sim Mode on,
-- it is simulated with the rest and the date moves on.
function Liga:prismLeaveTurnoverDay()
    local D = self.Date
    if D.preseasonDayPending and D:preseasonDayPending() then
        if not self.simMode then return end
        self.matchSimulator:simulateDayMatches(GLOBAL_DATE_PLACEHOLDER, true)
    end
    D:advanceDate()
end

function Liga:NoMatch()

    if self.isAutoAdvancing then

        self.backgroundProcessor:removeAnimTrack("dateSwipe")

        self.isAutoAdvancing = false; self.isAnimating = false

        self.transfersDoneForDate = {}; self.lastTransferDate = nil

        self.dateYPositions = {-100, -20, 60}

        self:dateAnim(); self:publishFinishLabel(); return

    end



    local liveState = self:_resolveNoMatchState()
    local isDeadline  = liveState.deadline
    local isSeasonEnd = liveState.seasonEnd

    if liveState.leagueEnded then
        self:endCareer()
        return
    end

    if isSeasonEnd then

        if sessionVars.get("InLeagueMode") then
            self:syncLeagueCompletion(true)
            self.isAutoAdvancing = false; self.isAnimating = false
            self.dateAdvanceCount = 0
            self:dateAnim(); self:publishFinishLabel()
        else
            self.SeasonInit:setNewSeason(function(self)

                self:prismLeaveTurnoverDay()

                self.transfersDoneForDate = {}; self.lastTransferDate = nil

                self.dateAdvanceCount = 0; self.isAutoAdvancing = false

                self.isAnimating = false; self.dateYPositions = {-100,-20,60}

                self:dateAnim(); self:publishFinishLabel()

                self.matchSimulator:simulateDayMatches(GLOBAL_DATE_PLACEHOLDER, self.simMode)

                updateTeamFormCache(self)

            end, self)
        end
        return

    elseif isDeadline then

        self.backgroundProcessor:removeAnimTrack("dateSwipe")

        self.isAutoAdvancing = false; self.dateYPositions = {-100,-20,60}

        self:dateAnim()

        self:animateDeadlineTime(function(deadlineReached)

            if not deadlineReached then

                self.im.Publish("bnd_advance_label","Advance One Hour")

                self:publishFinishLabel()

            end

        end); return

    elseif liveState.tourneyEnded then

        self:endCareer()
        return

    elseif liveState.matchday then

        self:PlayMatch()
        return

    end



    self.isAutoAdvancing = true

    if not self.dateAdvanceCount then self.dateAdvanceCount = 0 end



    local function advanceDateStep()

        if not self.isAutoAdvancing then return end

        if self.dateAdvanceCount >= 365 then

            self.isAutoAdvancing = false; self.isAnimating = false

            self.transfersDoneForDate = {}; self.lastTransferDate = nil

            self.backgroundProcessor:removeAnimTrack("dateSwipe")

            self.dateYPositions = {-100,-20,60}

            self:dateAnim(); self:publishFinishLabel()

            error("Maximum date advances reached; check match dates configuration")

            return

        end



        local homeID, awayID = findCurrentDayMatch(self, GLOBAL_DATE_PLACEHOLDER,

            self.simMode and 0 or currentSelectedTeamID)

        matchday = homeID ~= nil

        if matchday and sessionVars.get("InPlayerCareerMode") and self.playerCareer then

            local opponentID = (homeID == currentSelectedTeamID) and awayID or homeID

            self.playerCareer:pickAISquad(currentSelectedTeamID, opponentID)

        end



        if homeID or isDeadlineActive() or Date:isSeasonEnd() then

            self.isAutoAdvancing = false; self.isAnimating = false

            self.dateAdvanceCount = 0

            self.transfersDoneForDate = {}; self.lastTransferDate = nil

            self.dateYPositions = {-100,-20,60}

            self:dateAnim()



            if Date:isSeasonEnd() then

                if sessionVars.get("InLeagueMode") then
                    self:syncLeagueCompletion(true)
                    self:publishFinishLabel()
                else
                    self.SeasonInit:setNewSeason(function(self)

                        self:prismLeaveTurnoverDay(); self:publishFinishLabel()

                        self.matchSimulator:simulateDayMatches(

                            GLOBAL_DATE_PLACEHOLDER, self.simMode)

                        updateTeamFormCache(self)

                        self.nav.Event(nil,"evt_reload")

                    end, self)
                end

            elseif isDeadlineActive() then

                self.backgroundProcessor:removeAnimTrack("dateSwipe")

                self.isAutoAdvancing = false; self.dateYPositions = {-100,-20,60}

                self:dateAnim()

                self:animateDeadlineTime(function(deadlineReached)

                    if not deadlineReached then

                        self.im.Publish("bnd_advance_label","Advance One Hour")

                        self:publishFinishLabel()

                    end

                end)

            elseif matchday then
            
                if sessionVars.get("InPlayerCareerMode") and not (self.playerCareer:canPlayMatch()) then                           

                  self.im.Publish("bnd_advance_label","Sim Match")
                  
                else
                  self.im.Publish("bnd_advance_label","Matchday")
                end

            end

            return

        end



        self.matchSimulator:simulateDayMatches(GLOBAL_DATE_PLACEHOLDER, self.simMode)

        updateTeamFormCache(self)

        if self:syncLeagueCompletion(false) then
            self.isAutoAdvancing = false; self.isAnimating = false
            self.dateAdvanceCount = 0
            self.backgroundProcessor:removeAnimTrack("dateSwipe")
            self.dateYPositions = {-100,-20,60}
            self:dateAnim(); self:publishFinishLabel()
            return
        end

        self.dateAdvanceCount = self.dateAdvanceCount + 1

        self:animateDateSwipe(function() advanceDateStep() end)

    end



    advanceDateStep()

end



-- ── Matchday Animation ─────────────────────────────────────────────────────

-- Converted to BP animation track "matchdayAnim".

-- All five phases are driven by the same step counter and track.



function Liga:matchdayAnimInline(completionCallback, phase4Callback)

    self.backgroundProcessor:removeAnimTrack("matchdayAnim")

    self.isMatchdayAnimating = true



    local p1Dur, p3Dur, p4Dur, p5Dur, p6Dur = 0.2, 0.3, 1.0, 0.3, 0.1

    local stepInt = 0.016

    local p1Steps = math.max(1, math.floor(p1Dur / stepInt))

    local p3Steps = math.max(1, math.floor(p3Dur / stepInt))

    local p4Steps = math.max(1, math.floor(p4Dur / stepInt))

    local p5Steps = math.max(1, math.floor(p5Dur / stepInt))

    local p6Steps = math.max(1, math.floor(p6Dur / stepInt))

    local total   = p1Steps + p3Steps + p4Steps + p5Steps + p6Steps



    local iW,iH,iHX,iAX,iA = 55,55,-230,-160,1

    local p1TA = 0.5

    local p2W,p2H,p2A,p2HX,p2AX = 200,200,1,-50,150

    local p3HX,p3AX = -150,250

    local p5W,p5H,p5HX,p5AX = 55,55,-230,-160



    self.UItasks:_rowDisplay("hide")

    self.im.Publish("bnd_showAdvanceBtn", false)

    self.im.Publish("bnd_home_name",  ""); self.im.Publish("bnd_away_name",  "")

    self.im.Publish("bnd_homeRank",   ""); self.im.Publish("bnd_awayRank",   "")

    self.im.Publish("bnd_homeRankX",  ""); self.im.Publish("bnd_awayRankX",  "")

    self.im.Publish("bnd_matchup_label",""); self.im.Publish("bnd_matchdate_label","")

    self.im.Publish("bnd_league_label", ""); self.im.Publish("bnd_matchtag",     "")



    local step        = 0

    local phase4Fired = false

    local bp          = self.backgroundProcessor



    bp:registerAnimTrack("matchdayAnim", function()

        -- Cancellation check

        if not self.isMatchdayAnimating then

            bp:removeAnimTrack("matchdayAnim")

            self.im.Publish("crestsizeW",iW); self.im.Publish("crestsizeH",iH)

            self.im.Publish("cresthomeX",iHX); self.im.Publish("crestawayX",iAX)

            self.im.Publish("crestalpha",iA)

            self.UItasks:_rowDisplay("show")
            self:publishFinishLabel()

            if completionCallback then completionCallback() end

            return

        end



        step = step + 1



        if step > total then

            bp:removeAnimTrack("matchdayAnim")

            self.isMatchdayAnimating = false

            self.UItasks:_rowDisplay("show")
            self:publishFinishLabel()

            if completionCallback then completionCallback() end

            return

        end



        local isP1 = step <= p1Steps

        local isP3 = step > p1Steps and step <= (p1Steps+p3Steps)

        local isP4 = step > (p1Steps+p3Steps) and step <= (p1Steps+p3Steps+p4Steps)

        local isP5 = step > (p1Steps+p3Steps+p4Steps)

                 and step <= (p1Steps+p3Steps+p4Steps+p5Steps)

        local ps, pt, et



        if isP1 then

            ps = step; pt = ps/p1Steps; et = 1-(1-pt)*(1-pt)

            self.im.Publish("crestalpha", math.floor((iA+(p1TA-iA)*et)*100+0.5)/100)

            self.im.Publish("crestsizeW",iW); self.im.Publish("crestsizeH",iH)

            self.im.Publish("cresthomeX",iHX); self.im.Publish("crestawayX",iAX)

        elseif isP3 then

            ps = step-p1Steps; pt = ps/p3Steps; et = 1-(1-pt)*(1-pt)

            if ps == 1 then

                self.im.Publish("crestsizeW",p2W); self.im.Publish("crestsizeH",p2H)

                self.im.Publish("crestalpha",p2A)

                self.im.Publish("cresthomeX",p2HX); self.im.Publish("crestawayX",p2AX)

            end

            self.im.Publish("cresthomeX", math.floor(p2HX+(p3HX-p2HX)*et+0.5))

            self.im.Publish("crestawayX", math.floor(p2AX+(p3AX-p2AX)*et+0.5))

            self.im.Publish("crestsizeW",p2W); self.im.Publish("crestsizeH",p2H)

            self.im.Publish("crestalpha",p2A)

        elseif isP4 then

            self.im.Publish("crestsizeW",p2W); self.im.Publish("crestsizeH",p2H)

            self.im.Publish("cresthomeX",p3HX); self.im.Publish("crestawayX",p3AX)

            self.im.Publish("crestalpha",p2A)

        elseif isP5 then

            ps = step-(p1Steps+p3Steps+p4Steps); pt = ps/p5Steps; et = 1-(1-pt)*(1-pt)

            if ps == 1 and phase4Callback and not phase4Fired then

                phase4Callback(); phase4Fired = true

            end

            self.im.Publish("crestsizeW", math.floor(p2W+(p5W-p2W)*et+0.5))

            self.im.Publish("crestsizeH", math.floor(p2H+(p5H-p2H)*et+0.5))

            self.im.Publish("cresthomeX", math.floor(p3HX+(p5HX-p3HX)*et+0.5))

            self.im.Publish("crestawayX", math.floor(p3AX+(p5AX-p3AX)*et+0.5))

            self.im.Publish("crestalpha",p2A)

        else

            -- Phase 6 (final snap)

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("crestsizeW",iW); self.im.Publish("crestsizeH",iH)

            self.im.Publish("cresthomeX",iHX); self.im.Publish("crestawayX",iAX)

            self.im.Publish("crestalpha",iA)

            self:publishFinishLabel()

        end

    end, stepInt)

end



-- ── Update ─────────────────────────────────────────────────────────────────

-- Simplified: a single BP update drives all phases, including animation tracks.

-- The six individual timer update calls have been removed.



function Liga:update(elapsedTime)
    -- a few birthdates per frame, read ahead for the season end
    do local Y = rawget(_G, "PrismYouth"); if Y and Y.step then pcall(Y.step, 6) end end
    -- Diagnostics: one crumb per hub frame while PRISM_TRACE_FRAMES counts down from a deadline day.
    do local n = rawget(_G, "PRISM_TRACE_FRAMES"); if n and n > 0 then rawset(_G, "PRISM_TRACE_FRAMES", n - 1); do local c = rawget(_G, "PRISM_CRUMB"); if c then c("hub: frame " .. (9 - n) .. " of the new day") end end end end
    -- a screen change asked from a popup's answer (Liga:navAfterPopup), sent once the popup has closed
    do local p = self.prismNavAfterPopup
      if p then p.frames = p.frames - 1; if p.frames <= 0 then self.prismNavAfterPopup = nil; self.nav.Event(nil, p.event) end end end
    if prismFirstFrame then prismFirstFrame = false; prismLoadMark("hub: first frame") end
    do local CD = rawget(_G, "CareerDev"); if CD and CD.step then pcall(CD.step, 4) end end   -- a few player reads per frame
    do local PRO = rawget(_G, "PrismPro"); if PRO and PRO.step then pcall(PRO.step, self) end end   -- Player Career: offers for the user's player
    do local W = rawget(_G, "PRISM_WORLD"); if W and W.step then pcall(W.step, elapsedTime) end end   -- the lazy world: background fetch

    if self.backgroundProcessor then

        self.backgroundProcessor:update(elapsedTime)

    end

end



-- ── Match Actions ──────────────────────────────────────────────────────────



function Liga:KickOff(isKO)

    self.nav.Event(nil, isKO and "evt_advanceko" or "evt_advance")

end



--- Sends nav event `ev` two hub frames from now instead of at once: for a popup's answer, which runs inside the popup's
--- button handler while FCPopup closes it (evt_hide_overlay). Leaving the hub there took the popup and the hub down in
--- the same moment.
function Liga:navAfterPopup(ev)
    self.prismNavAfterPopup = { event = ev, frames = 2 }
    local c = rawget(_G, "PRISM_CRUMB"); if c then c("hub: " .. tostring(ev) .. " after the popup has closed") end
end

function Liga:Ineligible()

    self.FCPopup:getResponse(

        "Your squad has an ineligible player. \n Fix in Team Management",

        {"Fix"},

        function(r)

            if r == 1 then self:navAfterPopup("evt_squad") end

        end

    )

end



function Liga:endCareer()

    self.nav.Event(nil,"evt_back")

    sessionVars.set("InTourneyMode", false)

    sessionVars.set("InLeagueMode", false)

    sessionVars.set("InPlayerCareerMode", false)

    sessionVars.delete()

end



function Liga:exitCareer()

    self.FCPopup:getResponse(

        "Leaving without saving can cause unsaved work not to be saved, Do you want to proceed?",

        {"Yes","No"},

        function(r)

            if r == 1 then

                self.nav.Event(nil,"evt_back")

                sessionVars.set("InCareerMode",  false)

                sessionVars.set("InTourneyMode", false)

                sessionVars.set("InLeagueMode", false)

                sessionVars.set("InPlayerCareerMode", false)

                sessionVars.set("GLOBAL_DATE_PLACEHOLDER", GLOBAL_DATE_PLACEHOLDER)

                sessionVars.set("GLOBAL_FUNDS",  GLOBAL_FUNDS)

                sessionVars.set("isSuspended", isSuspended)

                rawset(_G, "PRISM_HUB_TAB", nil)
                self.ui:reset()

            end

        end

    )

end



function Liga:startSave(clbk)
    -- Save is intentionally fire-and-forget from MatchSelect.
    -- No confirmation/progress popup: invoke the serializer immediately.
    if clbk then clbk() end
end

function Liga:updateSave(msg, btn, clbk)
    -- Save progress is intentionally silent; retained as a compatibility hook
    -- for Serializer/older callers that still provide updateSave.
    if clbk then clbk() end
end



-- ── Finalize ───────────────────────────────────────────────────────────────

-- All six individual timer:finalize() calls replaced with removeAnimTrack().

-- BP:finalize() clears any remaining tracks automatically.



--- Shows msg in a popup with the buttons btn (default Ok) and calls clbk after the answer; used when a save did not
--- reach the disk. Replaces the two silent updateSave definitions above.
function Liga:updateSave(msg, btn, clbk)
    if msg and self.FCPopup then self.FCPopup:getResponse(msg, btn or {"Ok"}, clbk or function() end) return end
    if clbk then clbk() end
end

function Liga:finalize()
    -- the autosave handle belongs to this hub only
    if rawget(_G, "PRISM_SERIALIZER") == self.serializer then rawset(_G, "PRISM_SERIALIZER", nil) end

    -- Cancel any in-flight animation tracks (safe even if already absent).

    local bp = self.backgroundProcessor

    if bp then

        bp:removeAnimTrack("dateSwipe")

        bp:removeAnimTrack("deadlineAnim")

        bp:removeAnimTrack("matchdayAnim")

        bp:removeAnimTrack("newsAnim")

        bp:removeAnimTrack("swipeAnim")

        bp:removeAnimTrack("btnAnim")

        bp:finalize()

        self.backgroundProcessor = nil

    end



    self.im.UnregisterAction(ACT_ADVANCE)

    self.im.UnregisterAction(ACT_EXIT)

    self.im.UnregisterAction(PROGRESS)

    self.im.Unsubscribe(BND_DATE1)

    self.im.Unsubscribe(BND_DATE2)

    self.im.Unsubscribe(BND_DATE3)

    for i = 1, 3 do self.im.Unsubscribe("bnd_date"..i.."Y") end

    local unsubs = {

        "bnd_date_label","bnd_matchup_label","bnd_matchtag",

        "bnd_matchdate_label","bnd_league_label","bnd_advance_label",

        "bnd_month_label","bnd_finish_label","bnd_finance","bnd_financeextra",

        "bnd_home_crest","bnd_away_crest","bnd_home_name","bnd_away_name",

        "bnd_epl_visible","bnd_ads",

    }

    for _, name in ipairs(unsubs) do self.im.Unsubscribe(name) end

    if self.models.PlayerAge   then self.models.PlayerAge:finalize()   end

    -- AITransfers has no finalize
    if self.models.AITransfers and self.models.AITransfers.finalize then self.models.AITransfers:finalize() end

    -- the tab and card in use, for when the hub comes back
    if self.ui then rawset(_G, "PRISM_HUB_TAB", { tab = self.ui.currentTab, card = self.ui.selectedTab }) end
    self.ui:reset()

end



-- ── Prism Workers: the frames of the hub animations on the UI worker (see MatchSelect.patch.js) ─────────────

function Liga:displayNews(dir, callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (displayNewsInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:displayNewsInline(dir, callback) end

    -- The news card is open in its expanded/comments view - don't let the
    -- background cycle move or swap it out from under the user.
    if self.newsCenter and self.newsCenter.newsExpanded then
        if callback then callback() end
        return
    end

    dir = dir or 1

    -- Cancel any in-progress news animation; the new one takes over.

    self.backgroundProcessor:removeAnimTrack("newsAnim")

    self.isNewsAnimating = true



    local phaseDuration  = 0.15

    local stepInterval   = 0.016

    local stepsPerPhase  = math.max(1, math.floor(phaseDuration / stepInterval))

    local totalSteps     = stepsPerPhase * 2



    local phase1StartPos  = 20

    local phase1TargetPos = dir == 1 and -80 or 120

    local phase2StartPos  = dir == 1 and 120 or -80

    local phase2TargetPos = 20



    local step = 0

    local bp   = self.backgroundProcessor



    __J.animPlay(self, "newsAnim", {
        steps = totalSteps, ms = math.floor(stepInterval * 1000 + 0.5),
        channels = {
            { b = "news_position", a = 1, z = stepsPerPhase, from = phase1StartPos, to = phase1TargetPos, ease = "outQuad", round = "int" },
            { b = "news_alpha", a = 1, z = stepsPerPhase, from = 1, to = 0, ease = "outQuad", round = "c" },
            { b = "news_position", a = stepsPerPhase + 1, z = totalSteps, n = stepsPerPhase, from = phase2StartPos, to = phase2TargetPos, ease = "outQuad", round = "int" },
            { b = "news_alpha", a = stepsPerPhase + 1, z = totalSteps, value = 1 },
        },
        events = { [stepsPerPhase + 1] = { name = "swap", barrier = true } },
    }, {
        events = { swap = function()

                self.newsCenter:displayNews()

                self.im.Publish("news_position", phase2StartPos)

                self.im.Publish("news_alpha", 1)

        end },
        alive = function() return self.isNewsAnimating end,
        cancel = function()


            if callback then callback() end

        end,
        done = function()


            self.isNewsAnimating = false

            self.im.Publish("news_position", phase2TargetPos)

            self.im.Publish("news_alpha", 1)

            if callback then callback() end

        end,
    })
end

function Liga:animateDeadlineTime(callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (animateDeadlineTimeInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:animateDeadlineTimeInline(callback) end

    self.backgroundProcessor:removeAnimTrack("deadlineAnim")

    self.isAnimating = true

    self.im.Publish("bnd_showAdvanceBtn", false)

    self.im.Publish("bnd_isNotDateSim",   false)



    local stepInterval  = 0.04

    local totalSteps    = 60

    local currentHours  = math.floor(self.deadlineTime / 60)



    local function setDeadlineUI()

        self.im.Publish("bnd_date_label",    ""); self.im.Publish("bnd_month_label",   "")

        self.im.Publish("bnd_matchup_label", ""); self.im.Publish("bnd_matchdate_label","Time remaining")

        self.im.Publish("bnd_league_label",  ""); self.im.Publish("bnd_matchtag",      "")

        self.im.Publish("bnd_home_crest",  {}); self.im.Publish("bnd_away_crest",  {})

        self.im.Publish("matchleague",     {})

        self.im.Publish("bnd_home_name",   ""); self.im.Publish("bnd_away_name",   "")

        self.im.Publish("bnd_homeRank",    ""); self.im.Publish("bnd_awayRank",    "")

        self.im.Publish("bnd_homeRankX",   ""); self.im.Publish("bnd_awayRankX",   "")

        self.im.Publish("crestsizeW",  55); self.im.Publish("crestsizeH",  55)

        self.im.Publish("cresthomeX", -230); self.im.Publish("crestawayX", -160)

        self.im.Publish("crestalpha",   1)

    end



    -- Pre-animation setup (equivalent to the original onTimerComplete at step 0)

    if self.deadlineTime % 60 == 0 then

        currentHours = currentHours - 1

        if currentHours < 0 then

            -- Immediate completion (deadline already at 0)

            self.deadlineTime = 0

            self.im.Publish("bnd_advance_label",  "Deadline Passed")

            self.im.Publish("bnd_isdeadline",     false)

            self.im.Publish("bnd_deadlinetime",   "00:00")

            self.im.Publish("bnd_deadlinecolor",  "0xFF0D00")

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            setDeadlineUI()

            self.Date:advanceDate()

            self.deadlineTime = 10 * 60

            self:publishFinishLabel()

            self.isAnimating = false

            if callback then callback(true) end

            return

        end

        self.deadlineTime = currentHours * 60 + 59

    else

        self.deadlineTime = currentHours * 60 + 59

    end

    self:publishDeadlineTime(); setDeadlineUI()



    local step = 0

    local bp   = self.backgroundProcessor



    local __seqT, __seqC = {}, {}
    for __k = 1, totalSteps do
        local __m = 59 - (__k - 1)
        __seqT[__k] = string.format("%02d:%02d", currentHours, __m)
        __seqC[__k] = formatDeadlineColor(currentHours * 60 + __m)
    end
    __J.animPlay(self, "deadlineAnim", {
        steps = totalSteps, ms = math.floor(stepInterval * 1000 + 0.5),
        channels = {
            { b = "bnd_deadlinetime", a = 1, z = totalSteps, seq = __seqT },
            { b = "bnd_deadlinecolor", a = 1, z = totalSteps, seq = __seqC },
        },
    }, {
        alive = function() return self.isAnimating end,
        cancel = function()


            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            self:publishDeadlineTime(); setDeadlineUI()

            self.im.Publish("bnd_advance_label",

                self.deadlineTime <= 0 and "Deadline Passed" or "Advance One Hour")

            if callback then callback(false) end

        end,
        done = function()


            self.deadlineTime = currentHours * 60

            self:publishDeadlineTime(); setDeadlineUI()

            if currentHours <= 0 then

                self.deadlineTime = 0

                self.im.Publish("bnd_advance_label",  "Deadline Passed")

                self.im.Publish("bnd_isdeadline",     false)

                self.im.Publish("bnd_deadlinetime",   "00:00")

                self.im.Publish("bnd_deadlinecolor",  "0xFF0D00")

                self.im.Publish("bnd_showAdvanceBtn", true)

                self.im.Publish("bnd_isNotDateSim",   true)

                sessionVars.set("deadlineTime", nil)

                self.deadlineTime = 10 * 60

                -- Diagnostics: crumbs along the deadline -> new-day path, then a few hub frames.
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: the last hour ran out, advancing the date") end end
                self.Date:advanceDate()
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: date advanced to " .. tostring(GLOBAL_DATE_PLACEHOLDER) .. ", finish label next") end end
                self:publishFinishLabel()
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: finish label published") end end
                self.isAnimating = false
                if callback then callback(true) end
                do local c = rawget(_G, "PRISM_CRUMB"); if c then c("deadline: callback done; tracing the next hub frames") end end
                rawset(_G, "PRISM_TRACE_FRAMES", 8)

                return

            end

            self.im.Publish("bnd_showAdvanceBtn", true)

            self.im.Publish("bnd_isNotDateSim",   true)

            self.im.Publish("bnd_advance_label",  "Advance One Hour")

            sessionVars.set("deadlineTime", self.deadlineTime)

            self.isAnimating = false

            if callback then callback(false) end

        end,
    })
end

function Liga:animateDateSwipe(callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (animateDateSwipeInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:animateDateSwipeInline(callback) end

    self.backgroundProcessor:removeAnimTrack("dateSwipe")

    self.isAnimating = true

    -- No setAnimating(true, true): animation IS a BP track; pausing BP kills it.



    self.dateYPositions = {-100, -50, 0}

    self.im.Publish("bnd_date1Y", self.dateYPositions[1])

    self.im.Publish("bnd_date2Y", self.dateYPositions[2])

    self.im.Publish("bnd_date3Y", self.dateYPositions[3])

    self.im.Publish("bnd_dateAA3", 1)

    self.im.Publish("dateTS1", 20); self.im.Publish("dateTS2", 40)

    self:dateAnim()



    local totalDuration  = 0.3

    local phaseDuration  = 0.15

    local stepInterval   = 0.016

    local totalSteps     = math.max(1, math.floor(totalDuration  / stepInterval))

    local stepsPerPhase  = math.max(1, math.floor(phaseDuration  / stepInterval))



    local startY12  = {-100, -50}

    local targetY12 = {-50,    0}

    local startTS1, targetTS1  =  20,  40

    local startTS2, targetTS2  =  40,  20

    local p1StartY3, p1TargetY3, p1StartA, p1TargetA =    0, 30, 1, 0

    local p2StartY3, p2TargetY3, p2StartA, p2TargetA = -130, -100, 0, 1



    local step                   = 0

    local hasAdvancedDate        = false

    local pendingMatchdayAnim    = false

    local bp                     = self.backgroundProcessor



    __J.animPlay(self, "dateSwipe", {
        steps = totalSteps, ms = math.floor(stepInterval * 1000 + 0.5),
        channels = {
            { b = "bnd_date1Y", a = 1, z = totalSteps, from = startY12[1], to = targetY12[1], ease = "outQuad", round = "int" },
            { b = "bnd_date2Y", a = 1, z = totalSteps, from = startY12[2], to = targetY12[2], ease = "outQuad", round = "int" },
            { b = "dateTS1", a = 1, z = totalSteps, from = startTS1, to = targetTS1, ease = "outQuad", round = "int" },
            { b = "dateTS2", a = 1, z = totalSteps, from = startTS2, to = targetTS2, ease = "outQuad", round = "int" },
            { b = "bnd_date3Y", a = 1, z = stepsPerPhase, from = p1StartY3, to = p1TargetY3, ease = "outQuad", round = "int" },
            { b = "bnd_dateAA3", a = 1, z = stepsPerPhase, from = p1StartA, to = p1TargetA, ease = "outQuad", round = "c" },
            { b = "bnd_date3Y", a = stepsPerPhase + 1, z = totalSteps, n = stepsPerPhase, from = p2StartY3, to = p2TargetY3, ease = "outQuad", round = "int" },
            { b = "bnd_dateAA3", a = stepsPerPhase + 1, z = totalSteps, n = stepsPerPhase, from = p2StartA, to = p2TargetA, ease = "outQuad", round = "c" },
        },
        events = { [stepsPerPhase + 1] = { name = "advance", barrier = true } },
    }, {
        events = { advance = function()

                self.Date:advanceDate(); hasAdvancedDate = true

                local nextDate = self.DateUtils:getNextDay(GLOBAL_DATE_PLACEHOLDER)

                self.im.Publish(BND_DATE3, self.DateUtils:formatDateAsDayName(nextDate))

                local hID, aID = findCurrentDayMatch(self, GLOBAL_DATE_PLACEHOLDER,

                                                currentSelectedTeamID)

                matchday = hID ~= nil

                if matchday then

                    pendingMatchdayAnim = true

                    -- AI manager picks today's matchday squad right here, mid-swipe,
                    -- well before the date-advancement animation finishes, so that
                    -- PlayerCareer:canPlayMatch() / getPlayerSquadStatus() (and
                    -- anything else PlayerCareer exposes) reflect today's selection
                    -- as soon as the animation completes.
                    if sessionVars.get("InPlayerCareerMode") and self.playerCareer then
                        local opponentID = (hID == currentSelectedTeamID) and aID or hID
                        self.playerCareer:pickAISquad(currentSelectedTeamID, opponentID)
                    end                   
                end

                self.im.Publish("bnd_date3Y",  p2StartY3)

                self.im.Publish("bnd_dateAA3", p2StartA)

        end },
        alive = function() return self.isAnimating end,
        cancel = function()


            self:dateAnim()

            if callback then callback() end

        end,
        done = function()


            self.isAnimating = false

            self.dateYPositions = {-100, -50, 0}

            for i = 1, 3 do self.im.Publish("bnd_date"..i.."Y", self.dateYPositions[i]) end

            self.im.Publish("bnd_dateAA3", p2TargetA)

            self.im.Publish("dateTS1", 20); self.im.Publish("dateTS2", 40)

            self:publishDate1(); self:publishDate2(); self:publishDate3()

            self:publishFinishLabel()

            if pendingMatchdayAnim then

                self:matchdayAnim(function()

                    self.isAnimating = false

                    self:dateAnim(); self:publishFinishLabel()

                    if callback then callback() end

                end, function() end)

            else

                self.isAnimating = false

                self:dateAnim(); self:publishFinishLabel()

                if callback then callback() end

            end

        end,
    })
end

function Liga:animateTabButtons(tabsNum, btnTabsXConfig, direction, animationType, startOrTargetX, callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (animateTabButtonsInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:animateTabButtonsInline(tabsNum, btnTabsXConfig, direction, animationType, startOrTargetX, callback) end

    if not tabsNum or not btnTabsXConfig or tabsNum < 1 or not startOrTargetX then

        if callback then callback() end; return

    end

    self.backgroundProcessor:removeAnimTrack("btnAnim")

    self.isBtnAnimating = true



    local trackInterval = animationType == "fadeOut" and 0.033 or 0.016

    local buttonDelay   = animationType == "fadeOut" and 0.01  or 0

    -- Convert buttonDelay to "skip ticks" at the track interval.

    -- e.g. fadeOut: 0.01 / 0.033 ≈ 0.3 → 0 extra ticks (absorbed into interval).

    local skipPerButton = math.max(0, math.floor(buttonDelay / trackInterval))

    local steps         = math.max(1, math.floor(0.05 / trackInterval))



    local buttonOrder = {}

    for i = 1, tabsNum do

        buttonOrder[i] = direction == 1 and i or (tabsNum + 1 - i)

    end



    local step      = 0

    local skipCount = 0

    local totalSteps = tabsNum * steps

    local bp         = self.backgroundProcessor



    local __ch = {}
    for __i = 1, tabsNum do
        local bIdx    = buttonOrder[__i]
        local startX  = animationType == "fadeOut" and btnTabsXConfig[bIdx] or startOrTargetX
        local targetX = animationType == "fadeOut" and startOrTargetX or btnTabsXConfig[bIdx]
        local __a = (__i - 1) * (steps + skipPerButton) + 1
        __ch[#__ch + 1] = { b = "bnd_btnX" .. bIdx, a = __a, z = __a + steps - 1, from = startX, to = targetX, ease = "outQuad", round = "int" }
        __ch[#__ch + 1] = { b = "bnd_btnX" .. bIdx, a = __a + steps - 1, z = __a + steps - 1, value = targetX }
    end
    __J.animPlay(self, "btnAnim", {
        steps = tabsNum * (steps + skipPerButton), ms = math.floor(trackInterval * 1000 + 0.5), channels = __ch,
    }, {
        alive = function() return self.isBtnAnimating end,
        cancel = function()


            if callback then callback() end

        end,
        done = function()


            self.isBtnAnimating = false

            if callback then callback() end

        end,
    })
end

function Liga:swipeTabs(startX, targetX, callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (swipeTabsInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:swipeTabsInline(startX, targetX, callback) end

    self.backgroundProcessor:removeAnimTrack("swipeAnim")

    self.isSwipeAnimating = true



    local stepInt  = 0.016

    local duration = 0.09

    local steps    = math.floor(duration / stepInt)

    local stepSize = (targetX - startX) / steps

    local step     = 0

    local bp       = self.backgroundProcessor



    __J.animPlay(self, "swipeAnim", {
        steps = steps, ms = math.floor(stepInt * 1000 + 0.5),
        channels = { { b = "bnd_tabsPosX", a = 1, z = steps, from = startX, d = stepSize } },
    }, {
        alive = function() return self.isSwipeAnimating end,
        cancel = function()


            self.im.Publish("bnd_tabsPosX", targetX)

            if callback then callback() end

        end,
        done = function()


            self.isSwipeAnimating = false

            self.im.Publish("bnd_tabsPosX", targetX)

            if callback then callback() end

        end,
    })
end

function Liga:matchdayAnim(completionCallback, phase4Callback)
    -- Prism Workers: the frames of this animation are computed on the UI worker and written straight into the
    -- native screen; the stock version (matchdayAnimInline) runs without the workers or a native screen.
    local __J = rawget(_G, "PrismJobs")
    if not (__J and __J.animReady and __J.animReady(self)) then return self:matchdayAnimInline(completionCallback, phase4Callback) end

    self.backgroundProcessor:removeAnimTrack("matchdayAnim")

    self.isMatchdayAnimating = true



    local p1Dur, p3Dur, p4Dur, p5Dur, p6Dur = 0.2, 0.3, 1.0, 0.3, 0.1

    local stepInt = 0.016

    local p1Steps = math.max(1, math.floor(p1Dur / stepInt))

    local p3Steps = math.max(1, math.floor(p3Dur / stepInt))

    local p4Steps = math.max(1, math.floor(p4Dur / stepInt))

    local p5Steps = math.max(1, math.floor(p5Dur / stepInt))

    local p6Steps = math.max(1, math.floor(p6Dur / stepInt))

    local total   = p1Steps + p3Steps + p4Steps + p5Steps + p6Steps



    local iW,iH,iHX,iAX,iA = 55,55,-230,-160,1

    local p1TA = 0.5

    local p2W,p2H,p2A,p2HX,p2AX = 200,200,1,-50,150

    local p3HX,p3AX = -150,250

    local p5W,p5H,p5HX,p5AX = 55,55,-230,-160



    self.UItasks:_rowDisplay("hide")

    self.im.Publish("bnd_showAdvanceBtn", false)

    self.im.Publish("bnd_home_name",  ""); self.im.Publish("bnd_away_name",  "")

    self.im.Publish("bnd_homeRank",   ""); self.im.Publish("bnd_awayRank",   "")

    self.im.Publish("bnd_homeRankX",  ""); self.im.Publish("bnd_awayRankX",  "")

    self.im.Publish("bnd_matchup_label",""); self.im.Publish("bnd_matchdate_label","")

    self.im.Publish("bnd_league_label", ""); self.im.Publish("bnd_matchtag",     "")



    local step        = 0

    local phase4Fired = false

    local bp          = self.backgroundProcessor



    local __P3 = p1Steps + 1
    local __P4 = p1Steps + p3Steps + 1
    local __P5 = p1Steps + p3Steps + p4Steps + 1
    local __P6 = __P5 + p5Steps
    __J.animPlay(self, "matchdayAnim", {
        steps = total, ms = math.floor(stepInt * 1000 + 0.5),
        channels = {
            { b = "crestalpha", a = 1, z = p1Steps, from = iA, to = p1TA, ease = "outQuad", round = "c" },
            { b = "crestsizeW", a = 1, z = p1Steps, value = iW }, { b = "crestsizeH", a = 1, z = p1Steps, value = iH },
            { b = "cresthomeX", a = 1, z = p1Steps, value = iHX }, { b = "crestawayX", a = 1, z = p1Steps, value = iAX },
            { b = "cresthomeX", a = __P3, z = __P4 - 1, n = p3Steps, from = p2HX, to = p3HX, ease = "outQuad", round = "int" },
            { b = "crestawayX", a = __P3, z = __P4 - 1, n = p3Steps, from = p2AX, to = p3AX, ease = "outQuad", round = "int" },
            { b = "crestsizeW", a = __P3, z = __P5 - 1, value = p2W }, { b = "crestsizeH", a = __P3, z = __P5 - 1, value = p2H },
            { b = "crestalpha", a = __P3, z = __P6 - 1, value = p2A },
            { b = "cresthomeX", a = __P4, z = __P5 - 1, value = p3HX }, { b = "crestawayX", a = __P4, z = __P5 - 1, value = p3AX },
            { b = "crestsizeW", a = __P5, z = __P6 - 1, n = p5Steps, from = p2W, to = p5W, ease = "outQuad", round = "int" },
            { b = "crestsizeH", a = __P5, z = __P6 - 1, n = p5Steps, from = p2H, to = p5H, ease = "outQuad", round = "int" },
            { b = "cresthomeX", a = __P5, z = __P6 - 1, n = p5Steps, from = p3HX, to = p5HX, ease = "outQuad", round = "int" },
            { b = "crestawayX", a = __P5, z = __P6 - 1, n = p5Steps, from = p3AX, to = p5AX, ease = "outQuad", round = "int" },
            { b = "crestsizeW", a = __P6, z = total, value = iW }, { b = "crestsizeH", a = __P6, z = total, value = iH },
            { b = "cresthomeX", a = __P6, z = total, value = iHX }, { b = "crestawayX", a = __P6, z = total, value = iAX },
            { b = "crestalpha", a = __P6, z = total, value = iA },
        },
        events = { [__P5] = { name = "phase4" }, [__P6] = { name = "p6" } },
    }, {
        events = {
            phase4 = function() if phase4Callback and not phase4Fired then phase4Callback(); phase4Fired = true end end,
            p6 = function() self.im.Publish("bnd_showAdvanceBtn", true); self:publishFinishLabel() end,
        },
        alive = function() return self.isMatchdayAnimating end,
        cancel = function()


            self.im.Publish("crestsizeW",iW); self.im.Publish("crestsizeH",iH)

            self.im.Publish("cresthomeX",iHX); self.im.Publish("crestawayX",iAX)

            self.im.Publish("crestalpha",iA)

            self.UItasks:_rowDisplay("show")
            self:publishFinishLabel()

            if completionCallback then completionCallback() end

        end,
        done = function()


            self.isMatchdayAnimating = false

            self.UItasks:_rowDisplay("show")
            self:publishFinishLabel()

            if completionCallback then completionCallback() end

        end,
    })
end

return Liga
