local Brain, Processor, Savegame, Squads,
      glInstancePasser, Timer, sessionVars,
      Fixtures, CareerModeLeagues, LoadSave, Modes, SquadModel, SquadState = ...
local TeamSelect = {}
local TeamList = {}
local getTeamPls = nil
local getLeagueTms = nil
local getTeamLg = nil
-- The squad service captured when TeamSelect is built (for releasePlayer).
local prismSquadSvc = nil
local MAX_SHEET = 4 --Max team management sheets that can be created 

TeamListData = {}

local function deepCopy(orig)
    local copy = {}
    for k, v in pairs(orig) do
        if type(v) == "table" then
            copy[k] = deepCopy(v)
        else
            copy[k] = v
        end
    end
    return copy
end

local function debugTable(tbl, name)
end

local function reformatMatchDates(matchDates, globalDate)
    local reformattedDates = {}
    local day, month, year = globalDate:match("(%d+)/(%d+)/(%d+)")
    month = tonumber(month)
    year = tonumber(year)
    local oldYear, newYear
    if month >= 7 and month <= 12 then
        oldYear = year
        newYear = year + 1
    else
        oldYear = year - 1
        newYear = year
    end

    for i = 1, #matchDates do
        local date = matchDates[i]
        local dateStr = tostring(date)
        if #dateStr == 3 then
            dateStr = "0" .. dateStr
        end
        local matchMonth, matchDay = dateStr:match("(%d%d)(%d%d)")
        matchMonth = tonumber(matchMonth)
        local reformattedDate
        if month >= 7 and month <= 12 then
            if matchMonth >= 7 and matchMonth <= 12 then
                reformattedDate = dateStr .. string.format("%02d", oldYear)
            else
                reformattedDate = dateStr .. string.format("%02d", newYear)
            end
        else
            if matchMonth >= 1 and matchMonth <= 6 then
                reformattedDate = dateStr .. string.format("%02d", newYear)
            else
                reformattedDate = dateStr .. string.format("%02d", oldYear)
            end
        end
        reformattedDates[i] = reformattedDate
    end
    return reformattedDates
end

local function populateMatchData(schedule, reformattedDates, leagueID)
    local matchData = sessionVars.get("MatchData") or {}
    local leagueMatchData = sessionVars.get("LeagueMatchData") or {}
    leagueMatchData[leagueID] = leagueMatchData[leagueID] or {}
    local matchDataIndex = #matchData + 1
    local leagueMatchIndex = #leagueMatchData[leagueID] + 1
    local dateIndex = 1
    for i = 1, #schedule do
        local matchday = schedule[i]
        for j = 1, #matchday do
            local fixture = matchday[j]
            local matchEntry = {
                homeID = fixture[1],
                awayID = fixture[2],
                matchDate = reformattedDates[dateIndex],
                matchType = "League"
            }
            matchData[matchDataIndex] = matchEntry
            leagueMatchData[leagueID][leagueMatchIndex] = matchEntry
            matchDataIndex = matchDataIndex + 1
            leagueMatchIndex = leagueMatchIndex + 1
        end
        dateIndex = dateIndex + 1
    end
    sessionVars.set("MatchData", matchData)
    sessionVars.set("LeagueMatchData", leagueMatchData)
end

--- Writes "load: <msg>" to preview.log through F16Service (libpv stamps each line in ms): the career load's timeline.
local function prismLoadMark(msg)
    local f = rawget(_G, "F16_SVC")
    if f and f.Cmd then pcall(f.Cmd, "log:load: " .. msg) end
end
-- Sliced boot steps (Yield.patch.js): the heavy steps of the career boot run in slices, one per frame.
-- A slice lasts PRISM_SLICE seconds of process cpu (os.clock) or PRISM_SLICE_CALLS engine lineup calls (~38 ms each on
-- the phone), whichever comes first.
local PRISM_SLICE, PRISM_SLICE_CALLS = 0.3, 8
local prismJob = nil
--- Called by a step at a safe point. frac: how far the step is (0..1); label: what the loading screen says; calls: the
--- step's engine calls so far. Yields when the slice is used up; does nothing outside a sliced step.
local function prismLoadYield(frac, label, calls)
    local j = prismJob
    if not j or not coroutine or coroutine.running() ~= j.co then return end
    if frac then j.frac = frac end
    if label then j.label = label end
    if os.clock() - j.t0 >= PRISM_SLICE or (calls and calls - (j.calls0 or calls) >= PRISM_SLICE_CALLS) then
        j.calls0 = calls
        coroutine.yield()
    elseif calls and not j.calls0 then j.calls0 = calls end
end
rawset(_G, "PRISM_LOAD_YIELD", prismLoadYield)

--- Updates the loading screen: progress is the bar (bnd_progress), label the step line (bnd_prism_step).
function TeamSelect:prismShow(progress, label)
    local bar = self.loadingbar
    if not bar or not bar.im then return end
    if progress then pcall(bar.im.Publish, "bnd_progress", progress) end
    if label then pcall(bar.im.Publish, "bnd_prism_step", label) end
end

-- The stock game never calls the engine from a coroutine's own Lua thread, and a sliced step does. Should an engine
-- call not take that (a crash, the game closed mid-step), a marker in the career store (PrismBoot.json: m=slicing
-- while a sliced step runs, m=ok after it, m=noslice once slicing is off for good) tells the next boot: a boot that
-- finds a step left unfinished runs its steps in one go from then on.
local function prismStore(c)
    local f = rawget(_G, "F16_SVC")
    if not (f and f.Cmd and f.Out) then return nil end
    local ok, r = pcall(function() f.Cmd(c); return tostring(f.Out()) end)
    return ok and r or nil
end
local function prismMarkSlicing(state) prismStore("store:commit|PrismBoot.json|m=" .. state .. "|{}") end
local prismSliceOK = nil
local function prismSlicingAllowed()
    if prismSliceOK ~= nil then return prismSliceOK end
    local r = prismStore("store:status|PrismBoot.json") or ""
    prismSliceOK = true
    if r:find("m=noslice", 1, true) then prismSliceOK = false
    elseif r:find("m=slicing", 1, true) then
        prismSliceOK = false
        prismMarkSlicing("noslice")
        prismLoadMark("the last boot stopped inside a sliced step: the boot steps run in one go from now on")
    end
    return prismSliceOK
end
local function prismOneLine(s) return (tostring(s):gsub("%c", " ")):sub(1, 400) end

--- Runs body() a slice per frame, then done(). p0..p1: the progress bar's range for this step. rerun: the step can run
--- again from the start (the squad step builds everything in locals): a Lua error in a slice reruns it in one go.
function TeamSelect:prismSliced(p0, p1, label, body, done, rerun)
    self:prismShow(p0, label)
    local co = coroutine and coroutine.create and prismSlicingAllowed() and coroutine.create(body)
    if not co then body(); return done() end
    local job = { co = co, frac = 0, label = label, slices = 0 }
    local me = self
    local t0 = os.clock()
    prismMarkSlicing("slicing")
    local function resume()
        me.prismSliceTimer = nil
        prismJob = job
        job.t0 = os.clock(); job.slices = job.slices + 1
        local ok, err = coroutine.resume(co)
        prismJob = nil
        if not ok then
            -- the marker stays "slicing": whatever happens next, the next boot runs its steps in one go
            prismLoadMark(prismOneLine("step failed: " .. tostring(err) .. (debug and debug.traceback and (" | " .. debug.traceback(co)) or "")))
            if rerun then
                prismLoadMark("running that step again in one go")
                body()   -- an error in this run is the step's own: it stops the boot
                prismSliceOK = false
                prismMarkSlicing("noslice")
                prismLoadMark("it ran in one go: the boot steps run in one go from now on")
                return done()
            end
            error(err, 0)   -- an error in a step stops the boot where it is
        end
        if coroutine.status(co) == "dead" then
            prismMarkSlicing("ok")
            if job.slices > 1 then prismLoadMark(string.format("%s: %d slices, %.1f s of cpu", tostring(label), job.slices, os.clock() - t0)) end
            return done()
        end
        me:prismShow(p0 + (p1 - p0) * math.max(0, math.min(1, job.frac or 0)), job.label)
        me.prismSliceTimer = Timer:new({ id = "prismSlice", interval = 0.001, reps = 1, onTimerComplete = resume })
        me.prismSliceTimer:start()
    end
    resume()
end

--- Calls go() once the loading screen is on screen: its native screen said ready (PrismSkin counts them), or it is on
--- its stock layout (Prism off, the screen refused, or no PrismSkin at all), two frames on. At most ~90 frames.
function TeamSelect:prismWhenShown(go)
    local me, n, settle = self, 0, nil
    local function check()
        me.prismGateTimer = nil
        n = n + 1
        local PG = rawget(_G, "PRISM_SKIN")
        local shown = false
        if me.loadingbar then
            if type(PG) ~= "table" or PG.off or (type(PG.offScreens) == "table" and PG.offScreens.LoadingScreen) then shown = "stock layout"
            elseif ((type(PG.readyCount) == "table" and PG.readyCount.LoadingScreen) or 0) > (me.prismReadyBase or 0) then shown = "native" end
        end
        if shown and not settle then settle = n end
        if (settle and n - settle >= 2) or n >= 90 then
            prismLoadMark(string.format("loading screen %s after %d frames", shown and ("up (" .. shown .. ")") or "not confirmed", n))
            return go()
        end
        me.prismGateTimer = Timer:new({ id = "prismGate", interval = 0.001, reps = 1, onTimerComplete = check })
        me.prismGateTimer:start()
    end
    check()
end

function TeamSelect:new(init)
    local o = init or {}
    setmetatable(o, self)
    self.__index = self
    o.services = {
        SquadManagementService = o.api("SquadMgtService"),
        TeamService = o.api("TeamService"),
        TacticsService = o.api("TacticsService"),
        CountryService = o.api("CountryService")
    }
    prismSquadSvc = o.services.SquadManagementService   -- for the lazy club loads
    -- The lazy fetch (getCachedTeamPlayers) needs these on "Continue" too: that branch returns before they are set.
    getTeamPls = o.services.SquadManagementService.GetCurrentPlayerLineup
    getLeagueTms = o.services.TeamService.GetTeams
    getTeamLg = o.services.CountryService.GetLeagueInfoByTeamId
    o.loadmode = sessionVars.get("loadcareer") or false
    
    if sessionVars.get("CareerMode") and not(o.loadmode) then
      currentSelectedTeamID = sessionVars.get("currentSelectedTeamID")
      GLOBAL_DATE_PLACEHOLDER = sessionVars.get("GLOBAL_DATE_PLACEHOLDER")
      GLOBAL_FUNDS = sessionVars.get("GLOBAL_FUNDS")
      -- Put this mode's own globals back: another mode's career may have run in between and reset them.
      do local st = sessionVars.get("_prismGlobals")
        if type(st) == "table" then transferHistory = st.th or transferHistory; transferredPlayers = st.tp or transferredPlayers; CAREER_PLAYER_OVERRIDES = st.ovr or CAREER_PLAYER_OVERRIDES end
        CAREER_FULL_YEAR = tonumber((sessionVars.get("_careerFullYear"))) or CAREER_FULL_YEAR
        isSuspended = sessionVars.get("isSuspended") or isSuspended
      end
      o.nav.Event(nil, "evt_team_select")
      return o
    end
    
    o.Modes = Modes:new({nav = o.nav, loc = o.loc, api = o.api})
    o.loadSave = LoadSave:new({sessionVars = sessionVars, CareerModeLeagues = CareerModeLeagues, services = o.services, SquadState = SquadState})
    getTeamPls = o.services.SquadManagementService.GetCurrentPlayerLineup
    getLeagueTms = o.services.TeamService.GetTeams
    getTeamLg = o.services.CountryService.GetLeagueInfoByTeamId
    o.savegame = Savegame:new({api = o.api, Timer = Timer})
    o.savegame:openBrowser()
    o.squads = Squads:new({services = o.services})
    o.brain = Brain:new({squads = o.squads})
    o.processor = Processor:new({api = o.api, save = o.savegame})
    o.fixtures = Fixtures:new({save = o.savegame})
    o.test = "Instance Passed Successfully"
    o.allTeams = {}
    o.overlayTimer = nil
    o.initTimer = nil
    o.progress = 0
    o.loadingbar = nil
    o.progressDelayTimers = {}
    o.firstTime = not (sessionVars.get("CareerMode"))
    o.im.Subscribe("bnd_test", function()
        o.im.Publish("bnd_test", "It Stores State")
    end)
    

    -- the loading screen's ready count before it is asked for: prismWhenShown waits for it to rise
    do local PG = rawget(_G, "PRISM_SKIN"); o.prismReadyBase = type(PG) == "table" and type(PG.readyCount) == "table" and PG.readyCount.LoadingScreen or 0 end
    o.nav.Event(nil, "evt_show_overlay", {vvm = "/flows/mainflow/gamemodes/Liga/Screens/LoadingScreen.vvm", data = {getInstance = function(inst) o.loadingbar = inst end}})

    o.overlayTimer = Timer:new({
        id = "overlayTimer",
        interval = 0.15,   -- a few frames for the loading screen to appear
        reps = 1,
        onTimerComplete = function()
            o.overlayTimer = nil
            o.initTimer = Timer:new({
                id = "initTimer",
                interval = 0.05,   -- one frame
                reps = 1,
                onTimerComplete = function()             
                    o.initTimer = nil
                    -- the boot starts once the loading screen is up
                    o:prismWhenShown(function() o:startInitialization(currentSelectedTeamID) end)
                end
            })
            o.initTimer:start()
        end
    })
    o.overlayTimer:start()
    glInstancePasser:getInstance(o)
    return o
end

function TeamSelect:publishProgress(nextStepCallback)
    if self.loadingbar then
        self.loadingbar.im.Publish("bnd_progress", self.progress)
    end
    if nextStepCallback then
        local timer   -- declared first, so the callback below sees this local instead of the nil global
        timer = Timer:new({
            id = "progressDelay_" .. self.progress,
            interval = 0.05,   -- one frame after each step, so the progress bar still moves
            reps = 1,
            onTimerComplete = function()
                nextStepCallback()
                for i, t in ipairs(self.progressDelayTimers) do
                    if t.id == timer.id then
                        table.remove(self.progressDelayTimers, i)
                        break
                    end
                end
            end
        })
        table.insert(self.progressDelayTimers, timer)
        timer:start()
    end
end

function TeamSelect:startInitialization(teamId)
    displayMatchdayFixtures = nil   -- a Quick Match result must not open the career's results overlay
    local steps = {}
    local stepIndex = 1

    prismLoadMark("career " .. (self.loadmode and "load" or "start") .. ": steps begin")
    steps[1] = function()
        if not self.loadmode then   -- a new career has no save slot yet (its first save takes a free one)
            sessionVars.set("_prismSlot", nil); sessionVars.set("_prismCid", nil)
            local PS = rawget(_G, "PrismSlots"); if PS then PS.active = nil end
        end
        if self.firstTime then
            local shortlistedPlayers = {}
            sessionVars.set("currentSelectedTeamID", currentSelectedTeamID)
            sessionVars.set("GLOBAL_DATE_PLACEHOLDER", "01/07/25")
            GLOBAL_DATE_PLACEHOLDER = "01/07/25"
            sessionVars.set("PlayerDevInit", { mode = "new" })   -- player development
            sessionVars.set("_prismYouth", nil)   -- no youths yet (the hub makes the academy and the pool)
            CAREER_FULL_YEAR = 2025
            sessionVars.set("_careerFullYear", CAREER_FULL_YEAR)
            yellowCardRecords, redCardRecords, TeamFunds, injuryRecords, redCardMatchCount, injuryRecoveryDate, GOALS, matchdayLoaded, transferredPlayers = {}, {}, {}, {}, {}, {}, {}, {}, {}
            transferHistory = {}           
            -- the new career's transfer history starts empty
            sessionVars.set("transferLog", nil)
            local loanedPlayers = {}
            newSession = "yes"
            sessionVars.set("loanedPlayers", loanedPlayers)
            sessionVars.set("shortlistedPlayers", shortlistedPlayers)
            sessionVars.set("redMatchCount", {})
            -- a new career starts without the last career's pending cards, ban flags and injury dates
            do local Sx = rawget(_G, "PRISM_SUSP"); if Sx then Sx.pending = {}; Sx.pendingY = {}; Sx.cur = nil end end
            sessionVars.set("matchdayRedCard", {})
            sessionVars.set("injuryUntil", {})
            sessionVars.set("yellowCount", {})
            sessionVars.set("PlayerGoals", {})
            sessionVars.set("PlayerAssists", {})
            sessionVars.set("transferCount", 0)
            sessionVars.set("isSuspended", {})
            sessionVars.set("notListed", {})
            sessionVars.set("loanListed", {})
            sessionVars.set("transferListed", {})
            sessionVars.set("notFirstTime", {})
            SquadState.reset()
            sessionVars.set("tempSave", {})
            sessionVars.set("MatchData", {})
		    sessionVars.set("LeagueMatchData", {})
        end
        self.progress = 80
        self:publishProgress(function()
            stepIndex = stepIndex + 1
            if steps[stepIndex] then steps[stepIndex]() end
        end)
    end

    steps[2] = function()       
        prismLoadMark("step 2: squads")
        rawset(_G, "PRISM_WORLD_LAZY", self.loadmode and true or nil)   -- a saved career loads its world lazily
        self:prismSliced(80, 160, "Loading the squads", function() self.processor:cacheAllTeamPlayers() end, function()   -- a slice per frame
        prismLoadMark("step 2: squads done")
        self.progress = 160
        self:publishProgress(function()
            stepIndex = stepIndex + 1
            if steps[stepIndex] then steps[stepIndex]() end
        end)
    end, true)
    end

    steps[3] = function() self:prismSliced(160, 240, (self.firstTime and not self.loadmode) and "Setting up the season" or nil, function()   -- a slice per frame
        if self.firstTime then
            local allTeams = sessionVars.get("CareerModeTeams") or {}
            if (not self.loadmode) and sessionVars.get("InCareerMode") then
                local ctx = self.brain:buildInitialFinanceContext()
                prismLoadYield(0.25, "Setting up the season: budgets")
                sessionVars.set("GLOBAL_FUNDS", self.brain:calculateTeamFunds(nil, allTeams, true, ctx))
                prismLoadYield(0.5, "Setting up the season: fixtures")
            else
                -- Tournament and League modes intentionally have no finance layer.
                sessionVars.set("GLOBAL_FUNDS", {})
            end
            if (not self.loadmode) then
            local dateValue = GLOBAL_DATE_PLACEHOLDER or sessionVars.get("GLOBAL_DATE_PLACEHOLDER") or "01/07/25"
            local _, _, yy = dateValue:match("(%d%d)/(%d%d)/(%d%d)")
            local startYear = tonumber(rawget(_G, "CAREER_FULL_YEAR"))
                or tonumber((sessionVars.get("_careerFullYear")))
                or (2000 + (tonumber(yy) or 25))
            CAREER_FULL_YEAR = startYear
            sessionVars.set("_careerFullYear", startYear)
            local leagueTeams = sessionVars.get("LeagueTeams") or {}
            local userLeagueID = sessionVars.get("currentUserLeagueID") 
            local leagueMatchData = {}
            local matchData = {}
            local idx = 0
            if (sessionVars.get("InTourneyMode")) and (not(self.loadmode)) then
              
              if userLeagueID == 1000 then 
                sessionVars.set("GLOBAL_DATE_PLACEHOLDER", "06/06/26")
                startYear = 2026; CAREER_FULL_YEAR = 2026; sessionVars.set("_careerFullYear", 2026)   -- the World Cup is in 2026
              else
                sessionVars.set("GLOBAL_DATE_PLACEHOLDER", "01/09/25")
              end
              
              self.Modes:initializeMode(userLeagueID, startYear,nil, self.api)
            elseif sessionVars.get("InLeagueMode") then
              -- League Mode owns exactly one competition: the selected league.
              local teams = leagueTeams[userLeagueID] or {}
              self.fixtures:generateSchedule(teams, "automatic", startYear, userLeagueID)
            elseif sessionVars.get("InCareerMode") then
              for i = 1, #CareerModeLeagues do
                  local leagueID = CareerModeLeagues[i]
                  local teams = leagueTeams[leagueID] or {}
                  if leagueID ~= userLeagueID then
                    self.fixtures:generateSchedule(teams, "AI", startYear, leagueID)
                  else
                    self.fixtures:generateSchedule(teams, "automatic", startYear, leagueID)
                  end
                  prismLoadYield(0.5 + 0.5 * i / #CareerModeLeagues)
                --self.savegame:saveProgress(sessionVars.get("MatchData"))
              end

              -- Background UCL feeder standings. These leagues are deliberately
              -- not added to CareerModeLeagues, but they need real played tables
              -- so multi-season UCL qualification is performance-based.
              for _, leagueID in ipairs({4, 308}) do
                  local teams = leagueTeams[leagueID] or {}
                  if #teams >= 2 then
                      self.fixtures:generateSchedule(teams, "AI", startYear, leagueID)
                  end
              end
            end
          end
        end
        end, function()
        if self.loadmode then self:prismShow(nil, "Loading your save") end   -- painted in the frames before step 5
        self.progress = 240
        self:publishProgress(function()
            stepIndex = stepIndex + 1
            if steps[stepIndex] then steps[stepIndex]() end
        end)
    end) end

    steps[4] = function()
            
            
        self.progress = 320
        self:publishProgress(function()
            stepIndex = stepIndex + 1
            if steps[stepIndex] then steps[stepIndex]() end
        end)
    end

    steps[5] = function()
        if (self.loadmode) then
          prismLoadMark("step 5: the save")
          self.loadSave:loadSavedGame()
          prismLoadMark("step 5: the save loaded")
          do local W = rawget(_G, "PRISM_WORLD"); local st = W and W.state and W.state(); if st then st.quiet = false end end   -- loaded: a club asked for from now on gets its arrivals at once
        end
        -- keep this mode's career globals for its next load
        sessionVars.set("_prismGlobals", { th = transferHistory, tp = transferredPlayers, ovr = CAREER_PLAYER_OVERRIDES })
        sessionVars.set("loadcareer", nil)
        currentSelectedTeamID = sessionVars.get("currentSelectedTeamID")
        GLOBAL_DATE_PLACEHOLDER = sessionVars.get("GLOBAL_DATE_PLACEHOLDER")
        GLOBAL_FUNDS = sessionVars.get("GLOBAL_FUNDS")
        isSuspended = sessionVars.get("isSuspended") or {}
        -- Player Career: if the user just picked a team but hasn't yet picked
        -- their player, show the PlayerSelector overlay BEFORE entering the
        -- career hub. PlayerSelector.advance() will fire evt_team_select once
        -- the user confirms a player, resuming this boot flow's terminal step.
        -- (Skip when loadmode=true -- a loaded save already has PlayerCareerPlayerID.)
             
        if sessionVars.get("InPlayerCareerMode") and not sessionVars.get("PlayerCareerPlayerID") and not self.loadmode then
          self.nav.Event(nil, "evt_hide_overlay", {})
          -- Player Career (PrismPro): Create Your Player, or play as one of the club's squad (the PlayerSelector below)
          local PRO = rawget(_G, "PrismPro")
          local okS, took = false, false
          if PRO and PRO.start then okS, took = pcall(PRO.start, self, sessionVars) end
          if not (okS and took) then
          self.nav.Event(nil, "evt_show_overlay", {
            vvm = "/flows/mainflow/gamemodes/Liga/Screens/PlayerCareer/PlayerSelector/PlayerSelector.vvm",
            data = { nav = self.nav }
          })
          end
        else
          self.nav.Event(nil, "evt_team_select")
          self.nav.Event(nil, "evt_hide_overlay", {})
        end
    end

    steps[1]()
end

local function swapPlayersInTeam(players, cardIdToSwap)
			    if #players == 0 then return {} end
			    
			    local swapIdx, swapPos, foundIdx
			    for i, player in ipairs(players) do
			        if player.CARD_ID == cardIdToSwap then swapIdx, swapPos = i, player.position break end
			    end
			    if not swapIdx then return {} end
			    
			    for i = 12, #players do
			        if players[i].position == swapPos then
			            foundIdx = i			            			            
			        end
			    end   
			  return swapIdx, (foundIdx or 12)
			end


local function _careerDateParts()
    local ds = rawget(_G, "GLOBAL_DATE_PLACEHOLDER") or sessionVars.get("GLOBAL_DATE_PLACEHOLDER") or "01/07/25"
    local d, m, yy = ds:match("(%d%d)/(%d%d)/(%d%d)")
    d, m, yy = tonumber(d) or 1, tonumber(m) or 7, tonumber(yy) or 25
    local full = tonumber(rawget(_G, "CAREER_FULL_YEAR")) or tonumber((sessionVars.get("_careerFullYear")))
    if not full then full = 2000 + yy end
    if full % 100 ~= yy then
        local base = full - (full % 100) + yy
        if base < full - 50 then base = base + 100 elseif base > full + 50 then base = base - 100 end
        full = base
    end
    return d, m, full
end

local function _careerDateKey(year, month, day)
    return (tonumber(year) or 0) * 10000 + (tonumber(month) or 0) * 100 + (tonumber(day) or 0)
end

-- R98b loans (src/patches/ZzLoans.patch.js): window return dates, numeric ids after a load, one loan ended now.
--- The date key of the transfer window a loan made in month m of year y ends at: six months (halves 1) at the first window
--- opening (1 January / 1 July) at least four months on, a year (halves 2) at the first one at least ten months on.
function prismLoanReturnKey(y, m, halves)
    local add = (tonumber(halves) or 1) >= 2 and 10 or 4
    local tm = m + add
    local ty = y + math.floor((tm - 1) / 12); tm = (tm - 1) % 12 + 1
    if tm == 1 then return _careerDateKey(ty, 1, 1) end
    if tm <= 7 then return _careerDateKey(ty, 7, 1) end
    return _careerDateKey(ty + 1, 1, 1)
end

--- The career's loans with numeric ids and fields (a loaded save has the ids as strings), each with its window return
--- date; stored back in sessionVars and returned.
function prismLoanNormalize(loans)
    loans = loans or sessionVars.get("loanedPlayers") or {}
    local d, m, y = _careerDateParts()
    local out = {}
    for k, v in pairs(loans) do
        if type(v) == "table" then
            local rec = {}
            for f, x in pairs(v) do rec[f] = x end
            rec.duration = math.max(1, math.min(2, tonumber(rec.duration) or 1))
            rec.mainTeam = tonumber(rec.mainTeam) or rec.mainTeam
            rec.loanTeam = tonumber(rec.loanTeam) or rec.loanTeam
            rec.startDate = tonumber(rec.startDate)
            rec.returnDate = tonumber(rec.returnDate)
            if tonumber(rec.rule) ~= 2 then
                local sy, sm = y, m
                if rec.startDate then sy, sm = math.floor(rec.startDate / 10000), math.floor(rec.startDate / 100) % 100 end
                rec.startDate = rec.startDate or _careerDateKey(y, m, d)
                rec.returnDate = prismLoanReturnKey(sy, sm, rec.duration)
                rec.rule = 2
            end
            out[tonumber(k) or k] = rec
        end
    end
    sessionVars.set("loanedPlayers", out)
    return out
end

--- Ends player id's loan now: he leaves the club he is on loan at for his own. how ("recalled", "terminated", nil for the
--- end of the loan) is only logged. Returns true when the loan is over, else false and why.
function prismLoanEnd(playerID, how)
    local loans = prismLoanNormalize()
    local id = tonumber(playerID) or playerID
    local loanData = loans[id]
    if type(loanData) ~= "table" then return false, "not on loan" end
    local TeamCachedData = sessionVars.get("TeamCachedData") or {}
    local d, m, y = _careerDateParts()
    local today = _careerDateKey(y, m, d)
    local mainTeamID, loanTeamID = loanData.mainTeam, loanData.loanTeam
    local loanTeamPlayers = getCachedTeamPlayers(loanTeamID) or {}
    local playerToRevert, playerIndex
    for index = 1, #loanTeamPlayers do
        if tonumber(loanTeamPlayers[index].CARD_ID) == tonumber(id) then playerToRevert, playerIndex = loanTeamPlayers[index], index; break end
    end
    if not playerToRevert then
        -- already back at his club (an earlier version moved him without ending the loan): only the loan ends
        for _, p in ipairs(getCachedTeamPlayers(mainTeamID) or {}) do
            if tonumber(p.CARD_ID) == tonumber(id) then
                loans[id] = nil; transferredPlayers[id] = nil; sessionVars.set("loanedPlayers", loans)
                return true
            end
        end
        return false, "he is not at the loan club"
    end
    -- the starting XI keeps eleven: he leaves it first, as in a transfer
    if playerIndex <= 11 then
        local oldIdx, newIdx = swapPlayersInTeam(loanTeamPlayers, playerToRevert.CARD_ID)
        if oldIdx and newIdx then
            loanTeamPlayers[oldIdx], loanTeamPlayers[newIdx] = loanTeamPlayers[newIdx], loanTeamPlayers[oldIdx]
            playerIndex = newIdx
        end
    end
    table.remove(loanTeamPlayers, playerIndex)
    if TeamCachedData[loanTeamID] then TeamCachedData[loanTeamID].players = loanTeamPlayers end
    local mainTeamPlayers = getCachedTeamPlayers(mainTeamID) or {}
    playerToRevert.teamID = mainTeamID
    mainTeamPlayers[#mainTeamPlayers + 1] = playerToRevert
    TeamCachedData[mainTeamID] = TeamCachedData[mainTeamID] or {}
    TeamCachedData[mainTeamID].players = mainTeamPlayers
    if loanTeamID == teamId then players = loanTeamPlayers end
    if mainTeamID == teamId then players = mainTeamPlayers end
    SquadState.record(id, mainTeamID)
    for i = #transferHistory, 1, -1 do
        local record = transferHistory[i]
        if tonumber(record.Player) == tonumber(id) and record.isLoan then table.remove(transferHistory, i); break end
    end
    loans[id] = nil
    transferredPlayers[id] = nil
    -- the user's team sheets drop a loanee who left
    if loanTeamID == currentSelectedTeamID and not sessionVars.get("_isReplaying") then
        pcall(function()
            for i = 1, MAX_SHEET do
                local sheetData = sessionVars.get("sheetData")
                if sheetData and sheetData[i] then sheetData[i].players = SquadModel:syncWithLiveLineup(currentSelectedTeamID, sheetData[i].players, Squads) end
            end
        end)
    end
    -- Transfer History (PrismHistory): the end of a loan is a move back to the parent club
    do
        local H = rawget(_G, "PrismHistory")
        if H and H.record and not sessionVars.get("_isReplaying") then
            pcall(H.record, sessionVars, {
                id = id, name = playerToRevert.playerName, from = loanTeamID, to = mainTeamID, ret = true, date = today,
                user = loanTeamID == currentSelectedTeamID or mainTeamID == currentSelectedTeamID,
            })
        end
    end
    sessionVars.set("loanedPlayers", loans)
    sessionVars.set("TeamCachedData", TeamCachedData)
    print("[Loans] " .. tostring(playerToRevert.playerName) .. " (" .. tostring(id) .. ") " .. tostring(how or "loan over") .. ": " .. tostring(loanTeamID) .. " -> " .. tostring(mainTeamID))
    return true
end

--- R98d: the loan player id is on, seen from the user's club: "out" (the club loaned him out), "in" (he is at the club on
--- loan), "other" (a loan between two other clubs), and the loan; nil when he is not on loan.
function prismLoanInfo(playerID)
    local loans = sessionVars.get("loanedPlayers") or {}
    local l = loans[tonumber(playerID)] or loans[tostring(playerID)]
    if type(l) ~= "table" then return nil end
    local main, at, me = tonumber(l.mainTeam), tonumber(l.loanTeam), tonumber(currentSelectedTeamID)
    if main == nil or at == nil or main == at then return nil end
    if main == me then return "out", l end
    if at == me then return "in", l end
    return "other", l
end

--- R98d: every player on loan stays locked for transfers (transferredPlayers, which the AI and the transfer screens
--- check), by his number id: a loaded save has the loan ids as strings, and an older save restored no lock for them.
function prismLoanLock()
    if type(transferredPlayers) ~= "table" then return end
    for id, l in pairs(sessionVars.get("loanedPlayers") or {}) do
        if type(l) == "table" and tonumber(l.mainTeam) ~= tonumber(l.loanTeam) then transferredPlayers[tonumber(id) or id] = true end
    end
end

--- Moves a player between two clubs. isLoan / loanDuration (1 = six months, 2 = twelve) make it a loan; fee is
--- what the buyer paid (nil when not known) and is only read by the transfer history. Returns whether the
--- player moved.
function transferPlayer(playerID, sourceTeamID, targetTeamID, isLoan, loanDuration, isIntl, fee)
    local TeamCachedData = sessionVars.get("TeamCachedData")

    -- Guard: source team not cached (e.g. classic/national team from a previous session's
    -- realtime cache that was never persisted). getCachedTeamPlayers will attempt a lazy
    -- fetch via getTeamPls, but if that is also unavailable the entry stays nil.
    -- In that case we cannot replay the move, but we must still mark the player as
    -- transferred so AI cannot immediately re-sign them.
    if not TeamCachedData[sourceTeamID] then
        local _ = getCachedTeamPlayers(sourceTeamID)
    end
    
    if not TeamCachedData[sourceTeamID] then return false end
    
    local notFirstTime   = sessionVars.get("notFirstTime")
    local transferOffers = sessionVars.get("transferOffers") or {}

    if transferredPlayers[playerID] then
        return false
    end
    if not sessionVars.get("_isReplaying") and prismLoanInfo(playerID) then
        print("[Loans] " .. tostring(playerID) .. " is on loan: no transfer until the loan ends")
        return false
    end

    -- notFirstTime tracks the player's original club for display purposes only.
    -- It is intentionally NOT used when writing transfer history; sourceTeamID is
    -- always the actual current club and is what gets recorded.
    if not notFirstTime[playerID] then
        notFirstTime[playerID] = sourceTeamID
    end
    sessionVars.set("notFirstTime", notFirstTime)

    -- Get source team players
    local sourceTeamPlayers = getCachedTeamPlayers(sourceTeamID)
    if not sourceTeamPlayers or #sourceTeamPlayers == 0 then
        error("No players found for source teamID " .. sourceTeamID)
    end

    -- Find the player being transferred
    local playerToTransfer, playerIndex = nil, nil
    for index = 1, #sourceTeamPlayers do
        local player = sourceTeamPlayers[index]
        if player.CARD_ID == playerID then
            playerToTransfer = player
            playerIndex = index
            break
        end
    end
    if not playerToTransfer then
        return false
    end

    -- Swap out of starting XI before removal so the lineup stays valid
    if playerIndex <= 11 then
        local oldIdx, newIdx = swapPlayersInTeam(sourceTeamPlayers, playerID)
        if oldIdx and newIdx then
            sourceTeamPlayers[oldIdx], sourceTeamPlayers[newIdx] = sourceTeamPlayers[newIdx], sourceTeamPlayers[oldIdx]
            playerIndex = newIdx
        end
    end

    local soldPlayerPosition = playerToTransfer.position

    -- Remove from source
    table.remove(sourceTeamPlayers, playerIndex)
    TeamCachedData[sourceTeamID].players = sourceTeamPlayers

    -- Add to destination
    local targetTeamPlayers = getCachedTeamPlayers(targetTeamID)
    if not targetTeamPlayers or #targetTeamPlayers == 0 then
        targetTeamPlayers = {}
    end
    playerToTransfer.teamID = targetTeamID
    targetTeamPlayers[#targetTeamPlayers + 1] = playerToTransfer
    TeamCachedData[targetTeamID].players = targetTeamPlayers

    -- Keep active-team local reference in sync
    if targetTeamID == teamId then
        players = targetTeamPlayers
    end
    if sourceTeamID == teamId then
        players = sourceTeamPlayers
    end

    local transferCount = sessionVars.get("transferCount")

    -- Authoritative persistence records only the player's current club.
    -- transferHistory remains a display/news log; it is no longer replayed.
    -- A first move (no roster entry yet) notes the club he leaves as his origin.
    if SquadState.noteOrigin and SquadState.roster()[playerID] == nil then SquadState.noteOrigin(playerID, sourceTeamID) end
    SquadState.record(playerID, targetTeamID)

    -- Record the actual source team, never notFirstTime, so that reload can
    -- always find the player in the correct squad during history replay.
    transferHistory[#transferHistory + 1] = {
        Player  = playerID,
        oldTeam = sourceTeamID,
        newTeam = targetTeamID,
    }
    if isLoan then
        transferHistory[#transferHistory].isLoan = loanDuration
    end
    -- Transfer History (PrismHistory): one display record per move; a load replaying the roster records nothing
    if not sessionVars.get("_isReplaying") then
        local H = rawget(_G, "PrismHistory")
        if H and H.record then
            pcall(function()
                local d, m, y = _careerDateParts()
                H.record(sessionVars, {
                    id = playerID, name = playerToTransfer.playerName, from = sourceTeamID, to = targetTeamID,
                    date = _careerDateKey(y, m, d), fee = fee, loan = isLoan and (tonumber(loanDuration) or 1) or nil,
                    user = sourceTeamID == currentSelectedTeamID or targetTeamID == currentSelectedTeamID,
                })
            end)
        end
    end
    
    if not sessionVars.get("_isReplaying") then
      sessionVars.set("transferCount", transferCount + 1)    
    end
    
    --sessionVars.get("_isReplaying") check here ensures players aren't kicked out of the sheet tables before they are replayed back into TeamCachedData @set in LoadSave.lua
    if sourceTeamID == currentSelectedTeamID and not sessionVars.get("_isReplaying") then
  	for i = 1, MAX_SHEET do
        local sheetData = sessionVars.get("sheetData")
  	  if sheetData and sheetData[i] then
	      sheetData[i].players = SquadModel:syncWithLiveLineup(currentSelectedTeamID, sheetData[i].players, Squads)
	    end
  	end
	end
    -- Mark as transferred so the same player is not moved twice in one window
    transferredPlayers[playerID] = true

    -- Loan tracking. Store an absolute return date so "1 year" and "2 years"
    -- are actual elapsed calendar years instead of fixed January/June buckets.
    if isLoan then
        local loanedPlayers = sessionVars.get("loanedPlayers") or {}
        local d, m, y = _careerDateParts()
        -- loanDuration 1 = 6 months, 2 = 12 months (what Negotiate and the offers screen show)
        local ld = tonumber(loanDuration) or 1
        local halves = ld >= 12 and 2 or (ld >= 6 and 1 or math.max(1, math.min(2, ld)))
        loanedPlayers[playerID] = {
            duration = halves,
            mainTeam = sourceTeamID,
            loanTeam = targetTeamID,
            startDate = _careerDateKey(y, m, d),
            returnDate = prismLoanReturnKey(y, m, halves),   -- R98b: at a transfer window
            rule = 2,
        }
        sessionVars.set("loanedPlayers", loanedPlayers)
    end

    sessionVars.set("TeamCachedData", TeamCachedData)
    transferOffers[playerID] = nil
    sessionVars.set("transferOffers", transferOffers)
    return true   -- the player moved (every early exit above returns false)
end

function revertLoansByDuration(duration)
    -- R98b: numeric ids and window dates first (a loaded save), then every loan whose date has come ends
    local loanedPlayers = prismLoanNormalize()
    prismLoanLock()   -- R98d: whatever reset the lock (a new season, a load), the players on loan stay locked
    local d, m, y = _careerDateParts()
    local today = _careerDateKey(y, m, d)
    local due = {}
    for playerID, loanData in pairs(loanedPlayers) do
        if type(loanData) == "table" and tonumber(loanData.returnDate) and today >= tonumber(loanData.returnDate) then due[#due + 1] = playerID end
    end
    for _, playerID in ipairs(due) do prismLoanEnd(playerID) end
end

function releasePlayer(playerID, sourceTeamID)
    local TeamCachedData = sessionVars.get("TeamCachedData")
    local swapPlayer = false
    -- The career's squad (transfer-aware) and the service TeamSelect owns (`self` here is an unset global).
    local releaseSvc = (type(rawget(_G, "self")) == "table" and self.services and self.services.SquadManagementService) or prismSquadSvc
    local sourceTeamPlayers = getCachedTeamPlayers(sourceTeamID)
    if not sourceTeamPlayers and releaseSvc then sourceTeamPlayers = releaseSvc.GetCurrentPlayerLineup(0, sourceTeamID, 0) end
    if not sourceTeamPlayers or #sourceTeamPlayers == 0 then
        error("No players found for source teamID " .. sourceTeamID)
    end

    if sourceTeamID == currentSelectedTeamID then
        for i = 1, #sourceTeamPlayers do
            if sourceTeamPlayers[i].CARD_ID == playerID then
                if i <= 11 then
                    swapPlayer = true
                end
            end
        end
        if swapPlayer then
            local swapSuccess = swapPlayersInTeam(sourceTeamPlayers, playerID)
        end
    end

    local playerToRelease, playerIndex = nil, nil
    for index = 1, #sourceTeamPlayers do
        local player = sourceTeamPlayers[index]
        if player.CARD_ID == playerID then
            playerToRelease = player
            playerIndex = index
            break
        end
    end

    if not playerToRelease then
        return false
    end

    table.remove(sourceTeamPlayers, playerIndex)
    local updatedSourceTeamPlayerIDs = {}
    for i = 1, #sourceTeamPlayers do
        local player = sourceTeamPlayers[i]
        if player then
            updatedSourceTeamPlayerIDs[i] = player.CARD_ID
        end
    end
    if releaseSvc then releaseSvc.SetCurrentPlayerLineup(0, sourceTeamID, 0, 0, updatedSourceTeamPlayerIDs) end
    -- getCachedTeamPlayers may have added the club: read the cache table again.
    TeamCachedData = sessionVars.get("TeamCachedData")
    TeamCachedData[sourceTeamID].players = sourceTeamPlayers

    if sourceTeamID == teamId then
        players = sourceTeamPlayers
    end

    playerToRelease.teamID = nil
    transferredPlayers[playerID] = true
    -- Explicitly persist releases; otherwise a reboot would place the player
    -- back at their pristine API club.
    SquadState.release(playerID)
    sessionVars.set("TeamCachedData", TeamCachedData)
    return true
end

function TeamSelect:test()
    self.nav.Event(nil, "evt_back")
end

function TeamSelect:generateLigaGrouping()
    
end

function getCachedTeamPlayers(teamID)
    local TeamCachedData = sessionVars.get("TeamCachedData") or {}
    local _TeamCachedData = sessionVars.get("fifaSquad", true) or {}

    -- A cache entry with an empty players array is NOT a valid cache hit.
    -- This matters after switching modes: an older/partial League baseline
    -- could leave a team entry present but empty, which previously bypassed
    -- the lazy-cache branch and made Career transfer replay abort at 100%.
    local cachedEntry = TeamCachedData[teamID]
    local cachedPlayers = cachedEntry and cachedEntry.players
    local hasCachedPlayers = type(cachedPlayers) == "table" and #cachedPlayers > 0

    if not hasCachedPlayers and getTeamPls then
      local baselineEntry = _TeamCachedData[teamID]
      local baselinePlayers = baselineEntry and baselineEntry.players
      local hasBaselinePlayers = type(baselinePlayers) == "table" and #baselinePlayers > 0

      if hasBaselinePlayers then
        TeamCachedData[teamID] = deepCopy(baselineEntry)
      else
        -- pcall: GetCurrentPlayerLineup can throw for invalid/classic team IDs.
        -- Use the same service signature as Processor.lua.
        local okPls, plsResult = pcall(getTeamPls, 0, teamID, 0)
        local players = (okPls and type(plsResult) == "table") and plsResult or {}

        -- Resolve league safely; preserve an existing league tag if present.
        local leagueForCache = cachedEntry and cachedEntry.league
        if not leagueForCache then
          if sessionVars.get("InTourneyMode") then
            leagueForCache = sessionVars.get("currentUserLeagueID") or 1
          elseif getTeamLg then
            local okLg, lgResult = pcall(getTeamLg, teamID)
            leagueForCache = (okLg and lgResult and lgResult.id) or 1
          else
            leagueForCache = 1
          end
        end

        local repairedEntry = {
          players = deepCopy(players),
          league = leagueForCache
        }
        TeamCachedData[teamID] = repairedEntry

        -- Only promote a real lineup into the immutable global baseline.
        -- An unsupported/classic team returning no lineup stays retryable.
        if #players > 0 then
          _TeamCachedData[teamID] = deepCopy(repairedEntry)
          sessionVars.set("fifaSquad", _TeamCachedData, true)
        end
      end

      sessionVars.set("TeamCachedData", TeamCachedData)

      -- A club lazily materialised after load starts from the pristine API
      -- snapshot. Apply any roster entries involving it immediately so a
      -- transfer cannot silently revert just because the club was uncached.
      -- The club's youths in, rows of youths that are elsewhere out.
      do local Y = rawget(_G, "PrismYouth"); if Y and Y.inject then pcall(Y.inject, teamID) end end
      SquadState.applyPending(teamID)
    end

    local finalEntry = TeamCachedData[teamID]
    return finalEntry and finalEntry.players or false
end

function cacheTeamPlayers(teamID, players)
    local TeamCachedData = sessionVars.get("TeamCachedData")
    TeamCachedData[teamID] = {players = players}
    sessionVars.set("TeamCachedData", TeamCachedData)
end

function updateTeamLeague(leagueID, teamID)
    local TeamCachedData = sessionVars.get("TeamCachedData") or {}
    if not TeamCachedData[teamID] then   -- a club the lazy world has not fetched yet
        local W = rawget(_G, "PRISM_WORLD"); if W and W.ensure then pcall(W.ensure, teamID) end
        TeamCachedData = sessionVars.get("TeamCachedData") or {}
    end
    if TeamCachedData[teamID] then TeamCachedData[teamID].league = leagueID end
end

function getTeamLeague(teamID)
    local TeamCachedData = sessionVars.get("TeamCachedData") or {}   -- no cache (another mode's context) is no club
    if TeamCachedData[teamID] then return TeamCachedData[teamID].league or 1 end
    local W = rawget(_G, "PRISM_WORLD")   -- a club the lazy world has not fetched yet
    return (W and W.league and W.league(teamID)) or 1
end

function TeamSelect:update(elapsedTime)
    -- the boot gate and the slices are timed by the screen's own update
    if self.prismGateTimer then self.prismGateTimer:update(elapsedTime) end
    if self.prismSliceTimer then self.prismSliceTimer:update(elapsedTime) end
    if self.overlayTimer then
        self.overlayTimer:update(elapsedTime)
    end
    if self.initTimer then
        self.initTimer:update(elapsedTime)
    end
    for i = 1, #self.progressDelayTimers do
        self.progressDelayTimers[i]:update(elapsedTime)
    end
end

function TeamSelect:finalize()
    self.prismGateTimer = nil; self.prismSliceTimer = nil
    if self.overlayTimer then
        self.overlayTimer:finalize()
        self.overlayTimer = nil
    end
    if self.initTimer then
        self.initTimer:finalize()
        self.initTimer = nil
    end
    for i = 1, #self.progressDelayTimers do
        self.progressDelayTimers[i]:finalize()
    end
    self.progressDelayTimers = {}
    self.im.Unsubscribe("bnd_progress")
end

return TeamSelect
-- LEAGUE BY DAVUNPES --
-- REMODIFIED BY DAVUNPES --