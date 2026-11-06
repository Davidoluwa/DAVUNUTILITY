-- CareerDev.lua - the career glue for player development: wires PlayerDev.lua (the development model) and
-- MatchRating.lua (match ratings) into the Liga career.
--
-- PlayerDev is pure Lua: it is handed players and match results and returns what changed. CareerDev is the part that
-- knows the game. It reads players from the database, feeds PlayerDev, puts the result where the game looks, turns
-- matches into ratings and saves everything with the career. The file is installed as Liga/Data/CareerDev.lua
-- (patches/Career.patch.js), and the game's scripts reach it through guarded hooks of the form
--   local CD = rawget(_G, "CareerDev"); if CD and CD.fn then pcall(CD.fn, ...) end
-- so a missing module or a failing call leaves the stock game as it was. Everything lives in globals (CareerDev,
-- CAREER_DEV, PLAYER_DEV_STATE): each career screen runs its own copy of this file in the shared Lua state.
--
-- Hooks (game script -> CareerDev function)
--   Liga hub (MatchSelect)            bind and queueLeagueTeams when it is built; step on every update
--   MainHub (the main menu)           revertAll
--   Date:advanceDate                  onDate (a new calendar month develops the players)
--   SeasonInit:initSeason             onSeasonEnd
--   Serializer, LoadSave, TeamSelect  serialize into the save; a loaded save or a new career is handed over in
--                                     sessionVars "PlayerDevInit" and taken by the hub's bind
--   GameMenu (match-day result)       recordUserMatch
--   MatchSimulator                    recordSimMatch
--   Performa (ratings tab)            liveRatings
--   PlayerPerformance screen          liveRatings, performance, performanceStats, perfRatingColor
--   Match Facts (Events.lua)          matchAssists
--   MatchOverrides.patch.js           syncMatchOverrides, overridesStale
--   GetPlayerAge                      birthOf
--   World and MatchDay patches        refreshTeam, ovrOf
--   PrismProfile, PrismYouth          ensure, birthOf, overridesStale
--
-- Native access goes through F16Service only (global F16_SVC; Cmd(...) then Out()):
--   "db:<tagged int>"                reads (NativePlayerData's op protocol)
--   "db:setp:<id>:<field>=<v>,..."   writes the IN-MEMORY database (no file rewrite): squad screens, database reads
--                                    and the next match load see it at once
--   "db:caps"                        "setp-checked" when libpv looks the table up before it writes
--   "match:ratings", "match:log:0", "match:roster", "match:stats-names", "match:disarm"   the native match
--   "log:dev: <text>"                a line in libpv's preview.log
--
-- The moving parts
--
-- 1. PlayerDev state. PlayerDev.state (global PLAYER_DEV_STATE) is the development save:
--      { ver, seed, season, lastMonth = "<yy>-<mm>", players = { [databaseId] = p }, teamMatches }
--    A tracked player p keeps his current attributes `a` and his base attributes `b` (arrays in PlayerDev.ATTRS
--    order; b is what the database held when tracking began), his current overall `ovr` and the database overall
--    `ovr0`, plus pos, ir (international reputation), birth, pot (potential), form, team, rank and season tallies.
--    A player is in the state only once he has been tracked. Each mode (InCareerMode, InLeagueMode) keeps its own
--    state in its sessionVars context under "_prismDevState"; bind() takes it back when a career is resumed after
--    another mode ran in between.
--
-- 2. Tracking. queueLeagueTeams() queues the players of the user's league and club (squads from the career's squad
--    lookup); step() reads a few per frame from the hub's update (attributes, overall, potential, birthdate, position
--    and reputation, through NativePlayerData) and hands them to PlayerDev.track. ensure(id) tracks one player at
--    once. Generated youth players are tracked by PrismYouth instead.
--
-- 3. Calendar. onDate runs PlayerDev.monthTick when the month changes and applies the attribute changes it returns;
--    onSeasonEnd closes the season in PlayerDev.
--
-- 4. Where development becomes visible
--    Squad-cache rating refresh: the squad screens, team strength and the match simulator read a player's rating
--    from sessionVars "TeamCachedData"[teamId].players (rows with CARD_ID and rating). refreshCaches() and
--    refreshTeam() overwrite row.rating with the developed overall, and ovrOf() gives a screen the same number for
--    one row, so development shows everywhere without a database write.
--    Live database writes: setLive / applyAll / applyChange / revertAll put the values into the engine's in-memory
--    database. A live write can crash the engine, so it is gated (see setLive) and paused by default; the
--    development then stays in the state, the squad cache and the match overrides below. When writes are on, the
--    career's development is written when the career is entered and taken out again (back to the base values) when
--    another career or the main menu takes over, so a new career or a quick match starts from the database on disk.
--    Match overrides instead of live writes: the match engine plays everyone from the database. Right before a
--    match loads its teams, syncMatchOverrides fills the engine's match-time override table with the two clubs'
--    developed attributes (matchOverrides decides what fits and in which order) and the engine's player-loader hook
--    applies them to the match. Outside a career the table is emptied.
--
-- 5. Matches. recordUserMatch (the user's match) and recordSimMatch (every simulated fixture) turn a match into
--    rows { id, team, mins, goals, assists, yc, rc, rating? } and pass them to recordMatch, which lets PlayerDev
--    rate and record them (form, appearances, man of the match).
--    The user's match: userMatchModel reads lineups, events, the game's assist capture and the match facts from the
--    in-match services; userMatch rates it with the game's own ratings (nativeRatings, F16Service match:ratings) when
--    the native match has them, else MatchRating replays it from actions built out of the native per-player log
--    (nativeLog, match:log) or, without a log, from the scoresheet and the match facts. A match still on (pause menu,
--    half-time) is rated so far, up to the game clock.
--    A simulated match: recordSimMatch builds the XIs, substitutions, scorers, assists and cards from what
--    MatchSimulator generated.
--
-- 6. Ratings and performance screens. liveRatings is the one call every ratings screen makes, so the post-match
--    ratings tab, the Player Performance screen (performance / performanceStats) and the form PlayerDev stores show
--    the same numbers. Assists: countUserAssists adds the user's match assists to sessionVars "PlayerAssists";
--    matchAssists gives the Match Facts screen the assister of each goal from the engine's counters.
--
-- 7. Save. serialize() returns PlayerDev's save table for the career save (key playerDev); deserialize() and
--    newCareer() start a career from it or from the database. A save whose development data cannot be read sets
--    PRISM_SAVE_KEEPALL, so the session keeps every backup of the career store.
local CD = {}
-- Late-bound module accessors: the globals are looked up per call, and any of them may be absent.
local function PDm() return rawget(_G, "PlayerDev") end
local function NPDm() return rawget(_G, "NativePlayerData") end
local function svars() return rawget(_G, "CAREER_SESSION_VARS") end
-- The F16Service object (global F16_SVC) when it carries libpv's Cmd/Out, else nil. The members are probed under
-- pcall: a service object without them must not throw here.
local function F16()
  local f = rawget(_G, "F16_SVC")
  if f ~= nil and pcall(function() return f.Cmd ~= nil and f.Out ~= nil end) and f.Cmd ~= nil and f.Out ~= nil then return f end
  return nil
end

-- Session state (global CAREER_DEV), shared by every copy of this file:
--   queue, queued   players waiting to be read: a stack of { id, team, rank }, and the set of their ids
--   squad           the SquadManagementService used for the native player reads
--   log             the last 60 log lines (also sent to libpv's preview.log)
--   births          player id -> FIFA birthdate day number, or false when the database has none
--   applied         ids whose developed values were written into the live database (revertAll undoes them)
--   appliedCareer   the PlayerDev state applyAll last applied (nil: none yet)
--   active          a career is bound: matches are recorded only while it is true
--   readErr         number of failed player reads (the first five are logged)
--   overrideSig     signature of what was last written into the engine's match override table (nil: unknown)
--   assistsKey      the last user match whose assists were counted (see countUserAssists)
--   lastChanges     the changes of the last monthly tick
local G = rawget(_G, "CAREER_DEV")
if type(G) ~= "table" then
  G = { queue = {}, queued = {}, squad = nil, log = {}, births = {}, applied = {}, readErr = 0 }
  rawset(_G, "CAREER_DEV", G)
end
CD.G = G

-- Attribute name -> field id of the engine's player table (NativePlayerData's PLAYER_FIELD_ID, the <field> of db:setp).
local FIELD = { overallRating = 0, acceleration = 1, sprintSpeed = 2, agility = 3, balance = 4, jumping = 5, stamina = 6,
  strength = 7, reactions = 8, aggression = 9, interceptions = 10, positioning = 11, vision = 12, ballControl = 13,
  crossing = 14, dribbling = 15, finishing = 16, freeKickAccuracy = 17, headingAccuracy = 18, longPassing = 19,
  shortPassing = 20, marking = 21, shotPower = 22, longShots = 23, standingTackle = 24, slidingTackle = 25, volleys = 26,
  curve = 27, penalties = 28, gkDiving = 29, gkHandling = 30, gkKicking = 31, gkReflexes = 32, gkPositioning = 33 }
CD.FIELD = FIELD

--- Appends msg to the session log (the last 60 lines) and to libpv's preview.log.
local function log(msg)
  G.log[#G.log + 1] = msg
  if #G.log > 60 then table.remove(G.log, 1) end
  local f = F16()
  if f then pcall(f.Cmd, "log:dev: " .. tostring(msg)) end
end
CD.log = log

------------------------------------------------------------------------ binding
--- Binds the career to a screen. Any career screen that has an api may call it, repeatedly. It finds F16Service, keeps
--- the squad service and sessionVars, takes over a pending start and applies the career's development. A pending
--- start is sessionVars "PlayerDevInit": { mode = "load", data = <saved state> } from LoadSave or { mode = "new",
--- seed? } from TeamSelect; the previous career's changes are taken out of the database first.
--- @param api function?       the screen's service getter, api("F16Service")
--- @param services table?     { SquadMgtService = ... }, used for the native player reads
--- @param sessionVars table?  the career's sessionVars (get / set)
function CD.bind(api, services, sessionVars)
  if api ~= nil and F16() == nil then   -- the engine's api is a callable object on the phone, not a Lua function
    local ok, s = pcall(api, "F16Service")
    if ok and s then rawset(_G, "F16_SVC", s) end
  end
  if type(services) == "table" then G.squad = services.SquadMgtService or services.SquadManagementService or G.squad end
  if type(sessionVars) == "table" then rawset(_G, "CAREER_SESSION_VARS", sessionVars) end
  local sv = svars()
  local pend = sv and sv.get and sv.get("PlayerDevInit")
  if type(pend) == "table" then
    sv.set("PlayerDevInit", nil)
    CD.revertAll()
    if pend.mode == "load" then CD.deserialize(pend.data) else CD.newCareer(pend.seed) end
  end
  -- The development state belongs to this mode's context (sessionVars "_prismDevState"). A career that is started or
  -- loaded owns it; a career resumed after another mode ran in between takes its own state back.
  local PD = PDm()
  if PD and sv and sv.get and sv.set then
    local mine = sv.get("_prismDevState")
    if type(pend) == "table" or not mine then sv.set("_prismDevState", PD.state)
    elseif mine ~= PD.state and PD.adopt and PD.adopt(mine) then
      G.queue, G.queued, G.appliedCareer = {}, {}, nil
      log("development of this career restored after another mode ran (" .. CD.count() .. " players)")
    end
  end
  CD.applyAll()
  G.active = true
end

------------------------------------------------------------------------ dates
-- The career date (GLOBAL_DATE_PLACEHOLDER, "DD/MM/YY") as a FIFA day number; nil without PlayerDev or a date.
local function careerDay()
  local s = rawget(_G, "GLOBAL_DATE_PLACEHOLDER")
  local PD = PDm()
  return PD and s and PD.dayOfCareer(tostring(s)) or nil
end
-- "DD/MM/YY" -> "<yy>-<mm>", the month a development tick belongs to; nil for anything else.
local function monthKey(s) local d, m, y = tostring(s or ""):match("^(%d+)/(%d+)/(%d+)$"); return y and (y .. "-" .. m) or nil end

------------------------------------------------------------------------ in-memory database writes
--- Writes attribute values into the engine's in-memory database (the session's; the database file is never touched).
--- Live writes are gated: one that reaches a players table the live database has not loaded crashes the engine, so
--- they only run when libpv checks the table first, and NPD_LIVE_PAUSE (a reason string; false lifts the pause)
--- switches them off outright. While they are off this returns false and the development stays in the career state,
--- the squad cache and the match override table.
--- @param id number     player id
--- @param fields table  { [attributeName or "overallRating"] = value 1..99 }
--- @return boolean, any true, or false and the reason
local function setLive(id, fields)
  local NPD = NPDm()
  -- NativePlayerData applies the same gate and the same write, and drops the player from its read caches.
  if NPD and NPD.SetPlayerFieldsLive then
    local ok, err = NPD.SetPlayerFieldsLive(id, fields)
    return ok == true, err
  end
  local f = F16()
  if not f or not f.Cmd then return false, "F16Service unavailable" end
  -- Without NativePlayerData the same gate runs here. NPD_LIVE is the session's answer (true, or why writes are off);
  -- NPD_LIVE_PAUSE (a reason string) switches them off outright; otherwise libpv must report "setp-checked" for
  -- db:caps, i.e. it looks the table up in the live database before it writes.
  local st = rawget(_G, "NPD_LIVE")
  local pz = rawget(_G, "NPD_LIVE_PAUSE")
  if pz == nil then pz = "live database writes are paused (a live write crashed the game); development stays in the career and the squad screens" end
  if st == nil and pz then st = tostring(pz); rawset(_G, "NPD_LIVE", st) end
  if st == nil then
    local okC = pcall(f.Cmd, "db:caps")
    local okO, caps = pcall(f.Out)
    st = (okC and okO and tostring(caps or "") == "setp-checked") or "this libpv writes without checking the live database first"
    rawset(_G, "NPD_LIVE", st)
  end
  if st ~= true then return false, "live writes off: " .. tostring(st) end
  local parts = {}
  for name, v in pairs(fields) do local fid = FIELD[name]; if fid then parts[#parts + 1] = fid .. "=" .. math.floor(v) end end
  if #parts == 0 then return true end
  local ok, err = pcall(f.Cmd, "db:setp:" .. math.floor(id) .. ":" .. table.concat(parts, ","))
  if not ok then return false, err end
  local okO, out = pcall(f.Out)
  out = okO and tostring(out or "") or ""
  -- a refusal from libpv ("err:live <why>") turns the rest of the session's live writes off
  if out:sub(1, 9) == "err:live " then rawset(_G, "NPD_LIVE", out:sub(10)) end
  if out:sub(1, 4) == "err:" then return false, out end
  return true
end
CD.setLive = setLive
-- Why live writes are off for this session (nil while they are on or not tried yet).
local function liveOff() local st = rawget(_G, "NPD_LIVE"); return st ~= nil and st ~= true and tostring(st) or nil end
CD.liveOff = liveOff

--- Writes the career's development into the session's in-memory database: every tracked player whose attributes or
--- overall differ from the base values. It runs once per PlayerDev state (G.appliedCareer), then lets the squad cache
--- follow. When live writes are off for the session it stops at the first refusal.
function CD.applyAll()
  local PD = PDm()
  if not PD or G.appliedCareer == PD.state then return end
  local n = 0
  for id, p in pairs(PD.state.players) do
    local fields, any = {}, false
    if p.b then for i, name in ipairs(PD.ATTRS) do if p.a[i] ~= p.b[i] then fields[name] = p.a[i]; any = true end end end
    if p.ovr ~= p.ovr0 then fields.overallRating = p.ovr; any = true end
    if any then
      if setLive(id, fields) then G.applied[id] = true; n = n + 1
      elseif liveOff() then break end   -- off for the session: the rest is refused too
    end
  end
  G.appliedCareer = PD.state
  CD.refreshCaches()   -- squads cached before the hub bound hold database ratings
  if n > 0 then log("career development applied to " .. n .. " players") end
  if liveOff() then log("career development kept in the career and the squad screens, not the live database: " .. liveOff()) end
end
-- Entries sent per sync; the engine's override table holds 1024 values.
CD.OVERRIDE_MAX = 1000
--- The developed attribute values of the given clubs' players as match override entries { playerId, fieldName, value },
--- in priority order. The match engine reads its players from the game's database, which development cannot be written
--- into live (see setLive). The engine's match-time override table carries the developed values instead: right before a
--- match loads its teams (see syncMatchOverrides) they go into it through NativePlayerData.SetMatchOverrides, and the
--- engine's player-loader hook applies them to the match. The table holds 1024 values, so the order decides what fits:
---   1. the career editor's own edits (CAREER_PLAYER_OVERRIDES), which are always kept;
---   2. both clubs' starters (lineup rows 1-11), then their substitutes;
---   3. per player the overall first, then the attributes by size of change.
--- @param teams number[]  club ids
--- @return table[]        { { playerId, fieldName, value }, ... }
function CD.matchOverrides(teams)
  local PD = PDm()
  local entries, edited, seen = {}, {}, {}
  local stock = rawget(_G, "CAREER_PLAYER_OVERRIDES")
  if type(stock) == "table" then
    for rawId, fields in pairs(stock) do
      local id = tonumber(rawId)
      if id and type(fields) == "table" then
        for name, v in pairs(fields) do entries[#entries + 1] = { id, name, v }; edited[id .. ":" .. tostring(name)] = true end
      end
    end
  end
  if not PD then return entries end
  local sv = svars()
  local cache = sv and sv.get and sv.get("TeamCachedData") or {}
  -- A club's squad rows in lineup order: the career's squad cache, else the career's own lookup.
  local function rowsOf(tid)
    local e = type(cache) == "table" and cache[tid]
    if type(e) == "table" and type(e.players) == "table" and #e.players > 0 then return e.players end
    local fn = rawget(_G, "getCachedTeamPlayers")   -- a fixture's club is a real one: the career's own lookup
    if type(fn) == "function" then local ok, rows = pcall(fn, tid); if ok and type(rows) == "table" then return rows end end
    return {}
  end
  local function add(row)
    local id = type(row) == "table" and tonumber(row.CARD_ID or row.playerID)
    local p = id and not seen[id] and PD.get(id)
    -- a youth the career does not track: PrismYouth supplies a PlayerDev-like record
    if not p and id and not seen[id] then local Y = rawget(_G, "PrismYouth"); p = Y and Y.pdLike and Y.pdLike(id) or nil end
    if not p then return end
    seen[id] = true
    local list = {}
    -- the player's entries: the overall first (weight 1000), then the attributes by size of change
    if p.ovr and p.ovr0 and p.ovr ~= p.ovr0 then list[#list + 1] = { "overallRating", p.ovr, 1000 } end
    if p.b and p.a then
      for i, name in ipairs(PD.ATTRS) do
        if p.a[i] and p.b[i] and p.a[i] ~= p.b[i] then list[#list + 1] = { name, p.a[i], math.abs(p.a[i] - p.b[i]) } end
      end
    end
    table.sort(list, function(x, y) if x[3] ~= y[3] then return x[3] > y[3] end return x[1] < y[1] end)
    for _, f in ipairs(list) do if not edited[id .. ":" .. f[1]] then entries[#entries + 1] = { id, f[1], f[2] } end end
  end
  local lists = {}
  for k, tid in ipairs(teams or {}) do lists[k] = rowsOf(tid) end
  for _, rows in ipairs(lists) do for i = 1, math.min(11, #rows) do add(rows[i]) end end
  for _, rows in ipairs(lists) do for i = 12, #rows do add(rows[i]) end end
  return entries
end
--- Forgets what was last written into the engine's override table (G.overrideSig): the stock hub sync clears the
--- table, so the next syncMatchOverrides must write it again.
function CD.overridesStale() G.overrideSig = nil end
--- Fills the engine's match override table with the developed values of the two clubs about to play. Hooked right
--- before a match loads its teams: MatchSelect's PlayMatch, StartMatch and QuickStartMatch (MatchOverrides.patch.js).
--- Outside a career (a quick match) it empties the table instead, when it had filled it. A table that already holds
--- the same clubs and values is not written again.
--- @param teams number[]  the two clubs' ids
--- @param why string?     where the call comes from, for the log
--- @return boolean, any   true and the number of values in the table; false and the reason
function CD.syncMatchOverrides(teams, why)
  local NPD = NPDm()
  if not (NPD and NPD.SetMatchOverrides) then return false, "no match override writer" end
  -- outside a career nothing of a career belongs in the engine's table: empty it if it was filled here
  local sv = svars()
  if not (sv and sv.get and (sv.get("InCareerMode") or sv.get("InLeagueMode"))) then
    if G.overrideSig ~= nil then
      G.overrideSig = nil
      local ok, res = pcall(NPD.SetMatchOverrides, G.squad, {})
      log("in real matches: not a career match (" .. tostring(why or "match") .. "): the engine's override table emptied" .. ((ok and res) and "" or " (failed)"))
    end
    return false, "not in a career"
  end
  local list = {}
  for _, t in ipairs(teams or {}) do t = tonumber(t); if t and t > 0 then list[#list + 1] = t end end
  if #list == 0 then return false, "no clubs" end
  local entries = CD.matchOverrides(list)
  local total = #entries
  for i = total, CD.OVERRIDE_MAX + 1, -1 do entries[i] = nil end
  local parts = {}
  for i, e in ipairs(entries) do parts[i] = e[1] .. ":" .. tostring(e[2]) .. "=" .. tostring(e[3]) end
  local sig = table.concat(list, ",") .. "|" .. table.concat(parts, ";")
  if G.overrideSig == sig then return true, #entries end   -- already in the engine's table
  local ok, res, a, b = pcall(NPD.SetMatchOverrides, G.squad, entries)
  local players = {}
  for _, e in ipairs(entries) do players[e[1]] = true end
  local np = 0
  for _ in pairs(players) do np = np + 1 end
  if ok and res then
    G.overrideSig = sig
    log(string.format("in real matches (%s, clubs %s): %d developed attribute values for %d players%s", tostring(why or "match"),
      table.concat(list, " v "), a or #entries, np, total > #entries and string.format(" (%d more did not fit the engine's 1024)", total - #entries) or ""))
    return true, a or #entries
  end
  G.overrideSig = nil
  local err = ok and a or res
  log(string.format("in real matches (%s): the engine's override table refused after %s values: %s", tostring(why or "match"), tostring(ok and b or 0), tostring(err)))
  return false, err
end

--- Takes the career's development back out of the live database: every player written by applyAll / applyChange gets
--- his base values again. Called by the main menu and before another career is loaded or started, so a new career or
--- a quick match starts from the database as it is on disk.
function CD.revertAll()
  local PD = PDm()
  if not PD then return end
  local n = 0
  for id in pairs(G.applied) do
    local p = PD.state.players[id]
    if p and p.b then
      local fields = { overallRating = p.ovr0 }
      for i, name in ipairs(PD.ATTRS) do fields[name] = p.b[i] end
      if setLive(id, fields) then n = n + 1 end
    end
  end
  G.applied, G.appliedCareer, G.active = {}, nil, false
  if n > 0 then log("career development taken out of " .. n .. " players") end
end

------------------------------------------------------------------------ tracking
-- Reads one player from the database (attributes, bio, meta, birthdate) and starts tracking him in PlayerDev.
-- Returns true, or false and the reason.
local function readPlayer(id, team, rank)
  local NPD, PD = NPDm(), PDm()
  if not NPD or not PD then return false, "modules" end
  local svc = G.squad
  local attrs, err = NPD.GetPlayerAttributes(svc, id)
  if type(attrs) ~= "table" or attrs.error then return false, err or (attrs and attrs.error) end
  local bio = NPD.GetPlayerBio(svc, id)
  -- A generated youth: PrismYouth tracks his career values over the database row he plays in (that row's values are
  -- the base the match override table compares with).
  do local Y = rawget(_G, "PrismYouth"); if Y and Y.isYouth and Y.isYouth(id) then return Y.track(id, team, rank, attrs, bio and bio.overallRating) end end
  local meta = NPD.GetPlayerMeta and NPD.GetPlayerMeta(svc, id) or nil
  local birth = CD.birthOf(id)
  PD.track(id, { pos = attrs.preferredPosition1 or 25, ir = meta and meta.internationalReputation,
                 birth = birth or 0, pot = meta and meta.potential, ovr = bio and bio.overallRating, attrs = attrs,
                 team = team, rank = rank })
  return true
end

--- Queues the players of the given clubs that PlayerDev does not track yet for reading (see step). The players it
--- already tracks only get their club and squad rank (best rating = 1) refreshed. The squads come from the career's
--- lookup getCachedTeamPlayers.
--- @param teams number[]  club ids
--- @return number         players newly queued
function CD.queueTeams(teams)
  local getSquad = rawget(_G, "getCachedTeamPlayers")
  local PD = PDm()
  if type(getSquad) ~= "function" or not PD then return 0 end
  local n = 0
  for _, team in ipairs(teams or {}) do
    local ok, squad = pcall(getSquad, team)
    if ok and type(squad) == "table" then
      local list = {}
      for _, row in ipairs(squad) do local id = tonumber(row.CARD_ID or row.playerID or row.id); if id then list[#list + 1] = { id = id, r = tonumber(row.rating) or 0 } end end
      table.sort(list, function(a, b) return a.r > b.r end)
      for rank, it in ipairs(list) do
        if PD.get(it.id) then PD.track(it.id, { team = team, rank = rank })
        elseif not G.queued[it.id] then G.queued[it.id] = true; G.queue[#G.queue + 1] = { it.id, team, rank }; n = n + 1 end
      end
    end
  end
  return n
end
--- Queues the players of the user's league and of his club: the players the career plays against every week.
function CD.queueLeagueTeams()
  local sv = svars()
  local lt = sv and sv.get and sv.get("LeagueTeams")
  local league = sv and sv.get and sv.get("currentUserLeagueID")
  local teams, seen = {}, {}
  local mine = tonumber(rawget(_G, "currentSelectedTeamID"))
  if mine then teams[1] = mine; seen[mine] = true end
  local list = type(lt) == "table" and league and lt[league] or nil
  if type(list) == "table" then
    for _, t in pairs(list) do
      local id = tonumber(type(t) == "table" and (t.teamID or t.id or t.assetId) or t)
      if id and not seen[id] then seen[id] = true; teams[#teams + 1] = id end
    end
  end
  return CD.queueTeams(teams)
end

--- The hub's update hook: reads up to `budget` queued players (default 4), so a fresh career never stalls a frame.
--- @return number  players still queued
function CD.step(budget)
  local q = G.queue
  local done = 0
  while #q > 0 and done < (budget or 4) do
    local it = table.remove(q)
    local ok, err = readPlayer(it[1], it[2], it[3])
    if not ok then G.readErr = G.readErr + 1; if G.readErr <= 5 then log("cannot read player " .. tostring(it[1]) .. ": " .. tostring(err)) end end
    done = done + 1
  end
  if done > 0 and #q == 0 then log("tracking " .. CD.count() .. " players") end
  return #q
end
-- The number of players PlayerDev tracks.
function CD.count() local PD = PDm(); local n = 0; if PD then for _ in pairs(PD.state.players) do n = n + 1 end end return n end
--- Starts tracking one player now (a screen that needs his development state before the hub's queue reached him, e.g.
--- the player profile of a player from outside the user's league). Returns his PlayerDev state, or nil when he cannot
--- be read.
--- @param id number    the player's database id
--- @param team number? the club he plays for
function CD.ensure(id, team)
  local PD = PDm()
  id = tonumber(id)
  if not PD or not id then return nil end
  local p = PD.get(id)
  if p then return p end
  local ok, res = pcall(readPlayer, id, tonumber(team), nil)
  if not ok or res ~= true then return nil end
  return PD.get(id)
end

------------------------------------------------------------------------ real ages
--- A player's birthdate as a FIFA day number, for GetPlayerAge: the youth registry's for a generated youth, else the
--- tracked record's, else the database's (read once, cached for the session). It replaces the bundled birthdate
--- dictionary. nil when unknown.
--- @param id number
function CD.birthOf(id)
  id = tonumber(id)
  if not id then return nil end
  -- a generated youth has his own
  do local Y = rawget(_G, "PrismYouth"); local yb = Y and Y.birthOf and Y.birthOf(id); if yb then return yb end end
  local PD = PDm()
  local p = PD and PD.get(id)
  if p and p.birth and p.birth > 0 then return p.birth end
  local b = G.births[id]
  if b ~= nil then return b or nil end
  local NPD = NPDm()
  if not NPD or not NPD.GetBirthdateValue or not F16() then return nil end
  local ok, v = pcall(NPD.GetBirthdateValue, G.squad, nil, id)
  v = ok and tonumber(v) or nil
  G.births[id] = v or false
  return v
end

------------------------------------------------------------------------ writing changes
--- Squad-cache rating refresh: rewrites the rating of every cached squad row to the player's developed overall. The
--- squad cache (sessionVars "TeamCachedData"[teamId].players, rows with CARD_ID and rating) is what squad screens,
--- team strength and the match simulator read, so this is how development reaches them. One pass over the cache.
--- @param base boolean?  true writes the base (database) overall instead
--- @return number        rows changed
function CD.refreshCaches(base)
  local PD, sv = PDm(), svars()
  local cache = sv and sv.get and sv.get("TeamCachedData")
  if not PD or type(cache) ~= "table" then return 0 end
  local n = 0
  for _, team in pairs(cache) do
    local rows = type(team) == "table" and team.players
    if type(rows) == "table" then
      for _, row in pairs(rows) do
        local p = type(row) == "table" and PD.get(tonumber(row.CARD_ID or row.playerID))
        if p then
          local v = base and p.ovr0 or p.ovr
          if row.rating ~= v then row.rating = v; n = n + 1 end
        end
      end
    end
  end
  return n
end
--- refreshCaches for one club: used for a club the lazy world loads after the hub bound (refreshCaches only sees the
--- clubs cached by then). Always writes the developed overall.
--- @param teamID number
--- @return number  rows changed
function CD.refreshTeam(teamID)
  local PD, sv = PDm(), svars()
  local cache = sv and sv.get and sv.get("TeamCachedData")
  local team = type(cache) == "table" and cache[teamID]
  local rows = type(team) == "table" and team.players
  if not PD or type(rows) ~= "table" then return 0 end
  local n = 0
  for _, row in pairs(rows) do
    local p = type(row) == "table" and PD.get(tonumber(row.CARD_ID or row.playerID))
    if p and row.rating ~= p.ovr then row.rating = p.ovr; n = n + 1 end
  end
  return n
end

--- The overall a screen should show for a player: his developed overall when the career tracks him (PlayerDev, or the
--- youth registry for a generated youth), else `fallback`, else the squad row's own rating.
--- @param row table|number  a squad row (CARD_ID / playerID, rating) or a player id
--- @param fallback number?  used when the player is not tracked
function CD.ovrOf(row, fallback)
  local id = tonumber(type(row) == "table" and (row.CARD_ID or row.playerID) or row)
  local PD = PDm()
  local p = id and PD and PD.get(id)
  if not p and id then local Y = rawget(_G, "PrismYouth"); p = Y and Y.pdLike and Y.pdLike(id) or nil end
  if p and p.ovr then return p.ovr end
  if fallback ~= nil then return fallback end
  return type(row) == "table" and row.rating or nil
end
--- Writes one monthly change into the live database (see setLive).
--- @param ch table  an entry of PlayerDev.monthTick: { id, ovr, old, changed = { attributeName = value } }
--- @return boolean, any
function CD.applyChange(ch)
  local fields = {}
  for name, value in pairs(ch.changed or {}) do fields[name] = value end
  fields.overallRating = ch.ovr
  local ok, err = setLive(ch.id, fields)
  if ok then G.applied[ch.id] = true end
  return ok, err
end

------------------------------------------------------------------------ calendar
--- The month-change hook (Date:advanceDate). The first call only remembers the month. When the month differs from
--- PlayerDev.state.lastMonth it runs PlayerDev.monthTick, writes the changes live while that is allowed, refreshes
--- the squad cache and logs a summary line.
--- @param dateStr string?  "DD/MM/YY"; default the career date
--- @return table[]?        the tick's changes, see applyChange
function CD.onDate(dateStr)
  local PD = PDm()
  if not PD then return end
  local key = monthKey(dateStr or rawget(_G, "GLOBAL_DATE_PLACEHOLDER"))
  if not key then return end
  if PD.state.lastMonth == nil then PD.state.lastMonth = key; return end
  if key == PD.state.lastMonth then return end
  PD.state.lastMonth = key
  local changes = PD.monthTick(careerDay() or 0)
  local up, down, wrote = 0, 0, 0
  for _, ch in ipairs(changes) do
    -- into the live database only while it takes writes (liveOff() is nil): the development itself lives in the
    -- career state and the squad screens either way
    if not liveOff() and CD.applyChange(ch) then wrote = wrote + 1 end
    if ch.ovr > ch.old then up = up + 1 elseif ch.ovr < ch.old then down = down + 1 end
  end
  if #changes > 0 then CD.refreshCaches() end
  local db = ""
  if #changes > 0 then
    db = wrote == #changes and "; in the live database" or
      string.format("; live database: %d of %d written%s", wrote, #changes, liveOff() and (" (" .. liveOff() .. ")") or "")
  end
  log(string.format("month %s: %d players developed (%d up, %d down)%s", key, #changes, up, down, db))
  G.lastChanges = changes
  do local PRO = rawget(_G, "PrismPro"); if PRO and PRO.onMonth then pcall(PRO.onMonth) end end   -- Player Career: trust drifts
  return changes
end
--- The season-end hook (SeasonInit:initSeason): closes the season in PlayerDev (history, season tallies).
function CD.onSeasonEnd()
  local PD = PDm()
  if not PD then return end
  PD.seasonEnd(careerDay() or 0)
  log("season end -> season " .. tostring(PD.state.season))
  do local PRO = rawget(_G, "PrismPro"); if PRO and PRO.onSeasonEnd then pcall(PRO.onSeasonEnd) end end   -- Player Career: the season's line
end

------------------------------------------------------------------------ matches
-- The rows of the squad service's current lineup of one side (0 home, 1 away); {} when it cannot be read.
local function lineupOf(sq, side, team)
  local ok, rows = pcall(sq.GetCurrentPlayerLineup, side, team, 0)
  return ok and type(rows) == "table" and rows or {}
end
-- A lineup row's player id (the services name the field differently).
local function idOf(row) return tonumber(row.CARD_ID or row.cardId or row.playerId or row.playerID or row.assetId) end
-- Lower-case name without brackets and punctuation, for matching an event's name against a lineup.
local function clean(s) s = tostring(s or ""):lower():gsub("%b()", ""):gsub("[^%w]", ""); return s end
-- The player id of an event's player in a lineup: by jersey number first, else by (partial) name; nil if not found.
local function findId(lineup, name, number)
  local n = tonumber(number)
  for _, r in ipairs(lineup) do if n and tonumber(r.jerseyNumber or r.number) == n then local id = idOf(r); if id then return id end end end
  local c = clean(name)
  if c ~= "" then
    for _, r in ipairs(lineup) do
      local k = clean(r.playerName or r.name or r.commonName)
      if k ~= "" and (k:find(c, 1, true) or c:find(k, 1, true)) then local id = idOf(r); if id then return id end end
    end
  end
  return nil
end
-- The MatchRating module (nil when it is absent).
local function MRm() return rawget(_G, "MatchRating") end
-- A minute of the match as MatchRating replays it: "45+2'" -> 45.2 (stoppage time stays inside its half).
local function minuteOf(v)
  local s = tostring(v or "")
  local base, extra = s:match("(%d+)%s*%+%s*(%d+)")
  if base then return tonumber(base) + math.min(tonumber(extra), 9) / 10 end
  return tonumber(s:match("%d+")) or 0
end
CD.minuteOf = minuteOf
-- A substitution event names the player coming on.
local function isSub(d) return d.subInName ~= nil or d.subInNumber ~= nil end

-- The user's match from the in-match services (lineups: who started and the slot played; the events: goals, cards and
-- substitutions with their minutes; the game's captured assists, chronological across both teams; the match facts).
-- Returns nil when the services or the teams are missing, else
--   { home, away, len = 90 or 120,
--     players = { { id, team, posName, on, off, mins, goals, assists, yc, rc } },   on / off: minutes on the pitch
--     actions = { { t = minute, team, pid, k = "goal" | "yellow" | "red", own?, forTeam?, s?, assist? } },
--     facts = { [teamId] = team totals } or nil, lineups = { [teamId] = lineup rows } }
local function userMatchModel(svcs)
  local mi, sq = svcs.MatchInfoService or svcs.matchInfo, svcs.SquadManagementService or svcs.SquadMgtService
  if not mi or not sq then return nil end
  local okT, teams = pcall(mi.GetMatchTeams)
  if not okT or type(teams) ~= "table" or not teams[1] or not teams[2] then return nil end
  local home, away = tonumber(teams[1].assetId), tonumber(teams[2].assetId)
  local lineups = { [home] = lineupOf(sq, 0, home), [away] = lineupOf(sq, 1, away) }
  local other = { [home] = away, [away] = home }
  local rows, order = {}, {}
  local function row(id, team)
    if not rows[id] then rows[id] = { id = id, team = team, goals = 0, assists = 0, yc = 0, rc = 0 }; order[#order + 1] = id end
    return rows[id]
  end
  local okE, ev = pcall(mi.GetMatchEvents)
  local events = {}
  if okE and type(ev) == "table" then
    for _, side in ipairs({ { home, ev.homeData }, { away, ev.awayData } }) do
      for seq, e in ipairs(type(side[2]) == "table" and side[2] or {}) do
        local d = type(e) == "table" and (e.data or e) or {}
        events[#events + 1] = { team = side[1], d = d, t = minuteOf(d.minute), s = seq }
      end
    end
  end
  local len = 90
  for _, e in ipairs(events) do if e.t >= 100 then len = 120 end end
  -- who played: the XI from kick-off, substitutes from their minute (the events; the lineup's on-pitch flags when the
  -- events have no substitutions)
  local subs = false
  for _, e in ipairs(events) do if isSub(e.d) then subs = true end end
  for team, lu in pairs(lineups) do
    for i, r in ipairs(lu) do
      local id = idOf(r)
      if id then
        if i <= 11 then
          local x = row(id, team); x.posName = r.position; x.on = 0
          x.off = (not subs and r.playerOnPitch == false) and 65 or len
        elseif not subs and r.playerOnPitch == true then
          local x = row(id, team); x.posName = r.position; x.on = 65; x.off = len
        end
      end
    end
  end
  local actions, goals = {}, {}
  for _, e in ipairs(events) do
    local d, team = e.d, e.team
    if isSub(d) then
      local outId, inId = findId(lineups[team], d.name, d.number), findId(lineups[team], d.subInName, d.subInNumber)
      if outId and rows[outId] then rows[outId].off = math.min(rows[outId].off or len, e.t) end
      if inId then
        local x = row(inId, team); x.on = e.t; x.off = len
        for _, r in ipairs(lineups[team]) do if idOf(r) == inId then x.posName = x.posName or r.position end end
      end
    elseif d.eventId == 0 then
      local id, own = findId(lineups[team], d.name, d.number), false
      if not id then id = findId(lineups[other[team]], d.name, d.number); own = id ~= nil end   -- an own goal
      local g = { t = e.t, team = own and other[team] or team, pid = id, k = "goal", own = own or nil, s = e.s, forTeam = team }
      actions[#actions + 1] = g; goals[#goals + 1] = g
      if id then local x = row(id, g.team); if not own then x.goals = x.goals + 1 end end
    elseif d.eventId == 1 or d.eventId == 2 then
      local id = findId(lineups[team], d.name, d.number)
      if id then
        local x = row(id, team)
        if d.eventId == 1 then x.yc = x.yc + 1 else x.rc = 1 end
        actions[#actions + 1] = { t = e.t, team = team, pid = id, k = d.eventId == 1 and "yellow" or "red" }
      end
    end
  end
  -- the native assist slots are chronological across both teams (home first on the same minute, then list order)
  table.sort(goals, function(a, b)
    if math.floor(a.t) ~= math.floor(b.t) then return a.t < b.t end
    if a.forTeam ~= b.forTeam then return a.forTeam == home end
    return a.s < b.s
  end)
  local NPD = NPDm()
  for i, g in ipairs(goals) do
    if NPD and NPD.GetNativeGoalAssist and not g.own then
      local ok, aid = pcall(NPD.GetNativeGoalAssist, sq, i)
      aid = ok and tonumber(aid) or nil
      if aid and aid > 0 and aid ~= g.pid then
        local x = row(aid, g.team)
        if x.team == g.team then x.assists = x.assists + 1; g.assist = aid end
      end
    end
  end
  for _, id in ipairs(order) do
    local x = rows[id]
    x.on = x.on or 0; x.off = x.off or len
    x.mins = math.max(0, math.floor(x.off - x.on + 0.5))
  end
  -- the match facts (team totals)
  local facts
  local MR = MRm()
  local okF, f = pcall(mi.GetMatchFacts, true)
  if MR and okF and type(f) == "table" then
    local fh, fa = MR.factsFromRows(f.homeData), MR.factsFromRows(f.awayData)
    if fh and fa then facts = { [home] = fh, [away] = fa } end
  end
  local list = {}
  for _, id in ipairs(order) do list[#list + 1] = rows[id] end
  return { home = home, away = away, len = len, players = list, actions = actions, facts = facts, lineups = lineups }
end
CD.userMatchModel = userMatchModel

-- The score of the match (home goals, away goals) from the match info service; nil when unavailable.
local function scoreOf(mi)
  local ok, s = pcall(mi.GetMatchScore)
  if ok and type(s) == "table" then return tonumber(s.home or s.homeScore or s[1]), tonumber(s.away or s.awayScore or s[2]) end
end

-- The reply text of an F16Service command; nil when the command fails or the reply is empty, an error ("err...") or
-- starts with a control character.
local function f16Reply(f, cmd)
  if not pcall(f.Cmd, cmd) then return nil end
  local ok, s = pcall(f.Out)
  s = ok and tostring(s or "") or ""
  if s == "" or s:sub(1, 1) == "\1" or s:find("^err") then return nil end
  return s
end
--- The native per-player match log as MatchRating actions for the players of mm (userMatchModel). The log is libpv's
--- F16Service match:log: the game's AI::StatisticEngine counters, sampled during the match (the sampler is armed at
--- kick-off and disarmed by recordUserMatch).
---   match:stats-names   the counters' names, in index order
---   match:roster        "v1;<serial>;<side>,<slot>,<engine index>,<db id or 0>,<minutes>;..."
---   match:log:0         "v1;<serial>;<firstSeq>;<nextSeq>;<dropped>;<secs>,<side>,<slot>,<stat>,<delta>;..."
--- Identity: a slot is the player's place in the engine's team list (side 0 = home): the db id when libpv has it, else
--- the lineup row of that slot. The log is checked against the scoresheet (every scorer and booked player must show the
--- counter, and the slot with a side's keeper counters must be the lineup's goalkeeper). Clock: sampler seconds become
--- match minutes through the scoresheet's goals and cards (their counters' times).
--- @param home number
--- @param away number
--- @param mm table         the match model (userMatchModel)
--- @param recsOnly boolean?  return only the checked records, without building the actions (the Match Facts assists)
--- @return table|boolean|nil, table?, number?, string?, table?
---   the actions (true with recsOnly), the log header, the record count, "checked" | "unchecked" | "mismatch", the
---   records. nil when the APK has no log, the match logged nothing or the log's players do not fit the lineups.
function CD.nativeLog(home, away, mm, recsOnly)
  local f, MR = F16(), MRm()
  if not f or not MR then return nil end
  local names
  local s = f16Reply(f, "match:stats-names")
  if s then names = {}; for n in s:gmatch("[^,;]+") do names[#names + 1] = n end end
  local recs, hdr = MR.parseLog(f16Reply(f, "match:log:0") or "", names)
  if not recs or #recs < 20 then return nil end   -- nothing (or next to nothing) sampled: not a match's log
  local dbOf = {}
  local roster = f16Reply(f, "match:roster")
  for side, slot, db in (roster or ""):gmatch("(%d),(%d+),%-?%d+,(%d+)") do
    if tonumber(db) > 0 then dbOf[side .. "|" .. slot] = tonumber(db) end
  end
  mm = mm or {}
  local lineups = mm.lineups or {}
  local function idOfSlot(side, slot)
    local db = dbOf[side .. "|" .. slot]
    if db then return db end
    local lu = lineups[side == 0 and home or away]
    local row = type(lu) == "table" and lu[slot + 1]
    return row and idOf(row) or nil
  end
  -- the scoresheet check: the counters of every scorer / booked player (the slots mapped to him)
  local STAT = { goal = "GOALS", yellow = "YELLOW_CARDS", red = "RED_CARDS" }
  local count, firstT = {}, {}
  for _, r in ipairs(recs) do
    r.side = tonumber(r.side) or 0
    r.slot = r.pid
    r.pid = idOfSlot(r.side, r.slot)
    if r.pid and (r.delta or 0) > 0 then
      local k = r.pid .. "|" .. tostring(r.stat)
      count[k] = (count[k] or 0) + r.delta
      firstT[k] = firstT[k] or {}
      for _ = 1, r.delta do firstT[k][#firstT[k] + 1] = r.t end
    end
  end
  local checked, agree, anchors, used = 0, 0, {}, {}
  for _, a in ipairs(mm.actions or {}) do
    local stat = STAT[a.k]
    if stat and a.pid and not a.own then
      checked = checked + 1
      local k = a.pid .. "|" .. stat
      if (count[k] or 0) > 0 then
        agree = agree + 1
        used[k] = (used[k] or 0) + 1
        local t = firstT[k][used[k]]
        if t then anchors[#anchors + 1] = { t, a.t } end
      end
    end
  end
  -- the keepers: the slot with a side's keeper counters (saves, goal kicks, punches, dives at feet) must be the
  -- lineup's goalkeeper - a check that works in a 0-0 without cards too
  local GKS = { SAVES = 1, GOAL_KICKS = 1, PUNCHES_ATTEMPTED = 1, PUNCHES_COMPLETED = 1, DIVE_AT_FEET_ATTEMPTED = 1,
                DIVE_AT_FEET_COMPLETED = 1 }
  local gk = { [0] = {}, [1] = {} }
  for _, r in ipairs(recs) do
    if GKS[r.stat] and (r.delta or 0) > 0 and gk[r.side] then gk[r.side][r.slot] = (gk[r.side][r.slot] or 0) + r.delta end
  end
  for side = 0, 1 do
    local best, n = nil, 0
    for slot, c in pairs(gk[side]) do if c > n or (c == n and best and slot < best) then best, n = slot, c end end
    if best and n >= 2 then
      local lu = lineups[side == 0 and home or away]
      local row = type(lu) == "table" and not dbOf[side .. "|" .. best] and lu[best + 1]
      if row then
        checked = checked + 1
        if tostring(row.position or ""):upper() == "GK" then agree = agree + 1 end
      end
    end
  end
  if checked > 0 and agree < checked then
    log(string.format("match log: the players do not match the scoresheet (%d of %d events) - not used", agree, checked))
    return nil, hdr, #recs, "mismatch"
  end
  local t0, t1 = math.huge, -math.huge
  for _, r in ipairs(recs) do if r.t < t0 then t0 = r.t end; if r.t > t1 then t1 = r.t end end
  -- MINUTES_PLAYED is not a live clock (the engine latches it at goals and at full time), so the log is taken to cover
  -- kick-off .. full time and the anchors place what happened in between. For a match still on (the pause menu) it
  -- runs from kick-off to the game clock's minute so far, not to full time.
  local tm = MR.clockMap(anchors, t0, t1, 0, mm.now or mm.len or 90)
  local keep = {}
  for _, r in ipairs(recs) do if r.pid then keep[#keep + 1] = r end end
  if recsOnly then return true, hdr, #recs, checked > 0 and "checked" or "unchecked", keep end
  return MR.actionsFromStats(keep, home, away, tm), hdr, #recs, checked > 0 and "checked" or "unchecked", keep
end
CD.f16Reply = f16Reply

-- Seconds within which an ASSISTS tick is matched to a goal's GOALS tick (see assistsFromLog).
CD.ASSIST_WINDOW = 5
--- Assists from the game's own counters. The engine credits a goal's assist to the assister's ASSISTS counter in the
--- same evaluation as the scorer's GOALS (GoalEvaluation), so in the log they land in the same sample or within a
--- second or two. Each scoresheet goal without an assist (chronological) takes the scorer's next GOALS tick and the
--- nearest unused ASSISTS tick of a team-mate within ASSIST_WINDOW seconds.
--- @param recs table   the checked log records (nativeLog with recsOnly)
--- @param goals table  the scoresheet goals in capture-slot order (goalsInOrder); g.assist is filled in
--- @param home number
--- @return number      how many assists were found
function CD.assistsFromLog(recs, goals, home)
  local gt, at = {}, {}
  for _, r in ipairs(recs or {}) do
    if r.pid and (r.delta or 0) > 0 then
      if r.stat == "GOALS" then
        gt[r.pid] = gt[r.pid] or {}
        for _ = 1, r.delta do gt[r.pid][#gt[r.pid] + 1] = r.t end
      elseif r.stat == "ASSISTS" then
        for _ = 1, r.delta do at[#at + 1] = { t = r.t, side = r.side, pid = r.pid } end
      end
    end
  end
  local used, found = {}, 0
  for _, g in ipairs(goals or {}) do
    if g.pid and not g.own then
      used[g.pid] = (used[g.pid] or 0) + 1
      local tg = gt[g.pid] and gt[g.pid][used[g.pid]]
      if tg and not g.assist then
        local side = g.team == home and 0 or 1
        local best, bd
        for _, a in ipairs(at) do
          local d = math.abs(a.t - tg)
          if not a.used and a.side == side and a.pid ~= g.pid and d <= CD.ASSIST_WINDOW and (not bd or d < bd) then best, bd = a, d end
        end
        if best then best.used = true; g.assist = best.pid; found = found + 1 end
      end
    end
  end
  return found
end
-- The goals of a match model in the order of the game's capture slots: minute, home first, then event order.
local function goalsInOrder(mm)
  local goals = {}
  for _, a in ipairs(mm.actions or {}) do if a.k == "goal" then goals[#goals + 1] = a end end
  table.sort(goals, function(a, b)
    if math.floor(a.t) ~= math.floor(b.t) then return a.t < b.t end
    if a.forTeam ~= b.forTeam then return a.forTeam == mm.home end
    return (a.s or 0) < (b.s or 0)
  end)
  return goals
end
--- The Match Facts screen's assisters: for every goal, in the order of the game's capture slots (chronological, home
--- first within a minute), the assisting player's id or 0. They come from the capture slots where those have one and
--- from the engine's counters for the rest. nil without a usable log.
--- @param svcs table  { MatchInfoService, SquadManagementService }
--- @return number[]?
function CD.matchAssists(svcs)
  local mm = userMatchModel(svcs)
  if not mm then return nil end
  local _, _, _, _, recs = CD.nativeLog(mm.home, mm.away, mm, true)
  if not recs then return nil end
  local goals = goalsInOrder(mm)
  local n = CD.assistsFromLog(recs, goals, mm.home)
  local out = {}
  for i, g in ipairs(goals) do out[i] = tonumber(g.assist) or 0 end
  log(string.format("match facts: %d goal(s), %d assist(s) from the engine's counters", #goals, n))
  return out
end

-- Rates a match through MatchRating.rate. Returns the rating rows (with .rating) in the order of m.players, and
-- MatchRating's per-player table; nil when MatchRating is missing or fails.
local function rateRows(m)
  local MR = MRm()
  if not MR then return nil end
  local okR, res, list = pcall(MR.rate, m)
  if not okR or type(list) ~= "table" then log("match rating failed: " .. tostring(res)); return nil end
  local rows = {}
  for _, st in ipairs(list) do
    rows[#rows + 1] = { id = st.id, team = st.team, rating = st.rating, goals = st.goals, assists = st.assists, mins = st.mins,
                        yc = st.yc, rc = st.rc, posName = st.posName, line = st.line, n = st.n, on = st.on, off = st.off, conc = st.conc }
  end
  return rows, res
end
CD.rateRows = rateRows

--- The game's own ratings for the match just played, when libpv can read them from the native match: F16Service
--- match:ratings -> "v1;<motm id>;<id>,<side 0|1>,<rating x10>,<goals>,<assists>,<minutes>,<yellow>,<red>;...".
--- @return table?  { motm = id or nil, rows = { { id, team, rating, goals, assists, mins, yc, rc } } }, or nil when
---                 the native side has none (the Lua rating stands in)
function CD.nativeRatings(home, away)
  local f = F16()
  if not f or not f.Cmd then return nil end
  if not pcall(f.Cmd, "match:ratings") then return nil end
  local okO, out = pcall(f.Out)
  out = okO and tostring(out or "") or ""
  local motm, body = out:match("^v1;(%-?%d+);(.*)$")
  if not body then return nil end
  local t = { motm = tonumber(motm), rows = {} }
  if t.motm and t.motm <= 0 then t.motm = nil end
  for rec in body:gmatch("[^;]+") do
    local id, side, r10, g, a, mins, y, rc = rec:match("^(%d+),(%d),(%d+),(%d+),(%d+),(%d+),(%d+),(%d+)$")
    id = tonumber(id)
    if id and id > 0 then
      t.rows[#t.rows + 1] = { id = id, team = side == "0" and home or away, rating = tonumber(r10) / 10, goals = tonumber(g),
                             assists = tonumber(a), mins = tonumber(mins), yc = tonumber(y), rc = tonumber(rc) }
    end
  end
  if #t.rows == 0 then return nil end
  return t
end

--- Counted actions (n[k], MatchRating's keys) as a readable stat line.
--- @param n table      action counts
--- @param all boolean  true: the whole match (the main stats are always listed); else one player (only what he did)
function CD.statLine(n, all)
  n = n or {}
  local function c(k) return math.floor((n[k] or 0) + 0.5) end
  local parts = {}
  local function add(cond, fmt, ...) if all or cond then parts[#parts + 1] = string.format(fmt, ...) end end
  local shots = c("shot_on") + c("shot_off")
  add(shots > 0, "%d shots (%d on target)", shots, c("shot_on"))
  add(c("bigmiss") > 0, "%d big chances missed", c("bigmiss"))
  if c("pen_miss") > 0 then parts[#parts + 1] = string.format("%d penalties missed", c("pen_miss")) end
  add(c("keypass") + c("bigcreate") > 0, "%d chances created (%d big)", c("keypass") + c("bigcreate"), c("bigcreate"))
  if c("assist2") > 0 then parts[#parts + 1] = string.format("%d second assists", c("assist2")) end
  local pa = c("pass") + c("pass_bad") + c("pass_offside") + c("through_bad")
  add(pa > 0, "%d passes (%d misplaced, %d into offside)", pa, c("pass_bad") + c("through_bad"), c("pass_offside"))
  local cr = c("cross") + c("cross_bad")
  add(cr > 0, "%d crosses (%d completed)", cr, c("cross"))
  add(c("dribble") + c("dribble_bad") > 0, "%d dribbles (%d lost)", c("dribble") + c("dribble_bad"), c("dribble_bad"))
  if c("box") > 0 then parts[#parts + 1] = string.format("%d touches into the box", c("box")) end
  add(c("tackle") + c("tackle_bad") > 0, "%d tackles (%d lost)", c("tackle") + c("tackle_bad"), c("tackle_bad"))
  add(c("intercept") > 0, "%d interceptions", c("intercept"))
  add(c("clear") > 0, "%d clearances", c("clear"))
  add(c("header") + c("header_bad") > 0, "%d aerials (%d won)", c("header") + c("header_bad"), c("header"))
  add(c("save") > 0, "%d saves (%d big)", c("save"), c("save_big") + c("pen_save"))
  if c("pen_save") > 0 then parts[#parts + 1] = string.format("%d penalties saved", c("pen_save")) end
  if c("claim") + c("claim_bad") > 0 then parts[#parts + 1] = string.format("%d punches/rushes (%d failed)", c("claim") + c("claim_bad"), c("claim_bad")) end
  add(c("foul") > 0, "%d fouls", c("foul"))
  add(c("pen_conceded") > 0, "%d penalties conceded", c("pen_conceded"))
  add(c("offside") > 0, "%d offsides", c("offside"))
  add(c("error_shot") + c("error_goal") > 0, "%d errors leading to a shot, %d to a goal", c("error_shot"), c("error_goal"))
  if all then
    add(true, "%d goals, %d cards", c("goal"), c("yellow") + c("red"))
  end
  return table.concat(parts, ", ")
end

--- The match minute so far from the game clock ("34:12" -> 34.2): OverlayService.GetGameClockString, what the pause
--- menu's own timer shows. nil when there is no clock (the post-match tab: the match is over).
function CD.gameClock(svcs)
  local OS = type(svcs) == "table" and svcs.OverlayService
  if not OS then return nil end
  local okF, fn = pcall(function() return OS.GetGameClockString end)   -- (an engine service object: not necessarily a plain table)
  if not okF or not fn then return nil end
  local ok, s = pcall(fn)
  if not ok then return nil end
  local mnt, sec = tostring(s or ""):match("^%s*(%d+):(%d+)")
  if not mnt then return nil end
  return tonumber(mnt) + tonumber(sec) / 60
end

--- The user's match as PlayerDev rates it. The ratings are the game's own and its man of the match when the native
--- match has them; otherwise MatchRating replays the match, with the native per-player log (passes, dribbles,
--- offsides, fouls ...) when the APK records it, else from the scoresheet and the match facts. A match still on
--- (pause menu, half-time) is rated so far, up to the game clock.
--- @param svcs table   { MatchInfoService, SquadManagementService, OverlayService? }
--- @param hg number?   the final score, when the caller has it (default: read from MatchInfoService)
--- @param ag number?
--- @return table?  { date, home, away, hg, ag, len, now, lineups, players, and either native = true and motm (the
---                   game's ratings) or mode = "log" | "sheet", actSummary, names, logInfo }; players are rating rows
---                   when the game or MatchRating rated them, else the scoresheet rows (PlayerDev rates those)
function CD.userMatch(svcs, hg, ag)
  local mm = userMatchModel(svcs)
  if not mm then return nil end
  local home, away = mm.home, mm.away
  if hg == nil then hg, ag = scoreOf(svcs.MatchInfoService or svcs.matchInfo) end
  -- a match still on (paused, half-time) is rated so far, up to the game clock
  local now = CD.gameClock(svcs)
  if now then
    if now > 100 then mm.len = 120 end   -- (past 100: extra time; 90..100 is stoppage time of a 90-minute match)
    now = math.min(now, mm.len)
    if now >= mm.len - 0.01 then now = nil end   -- the full-time menu: the match is over
  end
  mm.now = now
  local m = { date = careerDay() or 0, home = home, away = away, hg = hg or 0, ag = ag or 0, players = mm.players, now = now }
  local nat = CD.nativeRatings(home, away)
  if nat then
    local pos = {}
    for _, r in ipairs(mm.players) do pos[r.id] = r.posName end
    for _, r in ipairs(nat.rows) do r.posName = pos[r.id] end
    m.players, m.motm, m.native, m.lineups, m.len = nat.rows, nat.motm, true, mm.lineups, mm.len or 90
    return m
  end
  local MR, PD = MRm(), PDm()
  if MR then
    local acts, mode = {}, "sheet"
    for _, a in ipairs(mm.actions) do acts[#acts + 1] = a end
    local logActs, hdr, nrec, check, recs = CD.nativeLog(home, away, mm)
    if logActs then CD.assistsFromLog(recs, goalsInOrder(mm), home) end   -- assists the capture slots missed
    local conceded = { [home] = 0, [away] = 0 }
    for _, a in ipairs(mm.actions) do if a.k == "goal" then local lose = (a.own and a.team or (a.team == home and away or home)); conceded[lose] = conceded[lose] + 1 end end
    local saves = {}
    if logActs then
      mode = "log"
      for _, a in ipairs(logActs) do
        acts[#acts + 1] = a
        if a.k == "save" then saves[a.team] = true end
        -- a penalty the engine saw go in: the scoresheet's goal by him nearest in time is a penalty (weighs 0.8)
        if a.k == "pen_goal" then
          local best, bd
          for _, g in ipairs(mm.actions) do
            if g.k == "goal" and not g.own and not g.pen and tonumber(g.pid) == tonumber(a.pid) then
              local dd = math.abs((tonumber(g.t) or 0) - (tonumber(a.t) or 0))
              if not bd or dd < bd then best, bd = g, dd end
            end
          end
          if best then best.pen = true end
        end
      end
    end
    -- the match facts: the keepers' saves when the log has none; in "sheet" also the team's offsides / fouls / tackles
    for _, a in ipairs(MR.sheetActions(mm.players, mm.facts, home, away, conceded, mm.len)) do
      if (mode == "sheet") or (a.k == "save" and not saves[a.team]) then acts[#acts + 1] = a end
    end
    -- the slot played decides the line; the player's own position when the lineup has no slot name
    local slot = {}
    if PD and PD.POSCODE then for k, v in pairs(PD.POSCODE) do slot[v] = k end end
    for _, r in ipairs(mm.players) do
      local p = PD and PD.get and PD.get(r.id)
      r.pos = p and slot[p.pos] or nil
    end
    local rows = rateRows({ date = m.date, seed = PD and PD.state and PD.state.seed, home = home, away = away, len = mm.len,
                            now = now, mode = mode, players = mm.players, actions = acts, facts = mm.facts })
    -- what fed the ratings, for the log (the end-of-match screen writes one summary line)
    local n = {}
    for _, a in ipairs(acts) do n[a.k] = (n[a.k] or 0) + (tonumber(a.w) or tonumber(a.n) or 1) end
    m.actSummary = CD.statLine(n, true)
    m.names = {}
    for _, lu in pairs(mm.lineups or {}) do for _, r in ipairs(lu) do local id = idOf(r); if id then m.names[id] = r.playerName end end end
    if rows then
      m.players, m.mode, m.lineups, m.len = rows, mode, mm.lineups, mm.len or 90
      m.logInfo = hdr and string.format("%d records, serial %s, dropped %s, players %s", nrec or 0, tostring(hdr.serial),
                                        tostring(hdr.dropped), tostring(check)) or nil
    end
  end
  return m
end

--- The end-of-match ratings: every player's rating ranked (man of the match first), exactly what recordUserMatch
--- stores. Used by the ratings tab (Performa) and the Player Performance screen, and logs one summary line per match.
--- @param svcs table   see userMatch
--- @param hg number?
--- @param ag number?
--- @return table?  { motm, list = ranked { id, team, rating, goals, assists, mins, yc, rc }, native, mode, home, away,
---                   hg, ag, lineups, len, now, rows = { [id] = rating row with MatchRating's counts in .n },
---                   [id] = rating }
function CD.liveRatings(svcs, hg, ag)
  local PD = PDm()
  if not PD then return nil end
  local m = CD.userMatch(svcs, hg, ag)
  if not m then return nil end
  local list, motm = PD.rateMatch(m)
  local out = { motm = motm, list = list, native = m.native == true, mode = m.mode, home = m.home, away = m.away, hg = m.hg, ag = m.ag,
                lineups = m.lineups, len = m.len, now = m.now, rows = {} }
  -- rows by id, for the Player Performance screen
  for _, r in ipairs(m.players or {}) do if r.id then out.rows[r.id] = r end end
  for _, x in ipairs(list) do out[x.id] = x.rating end
  -- one line per ratings screen: the source, the man of the match, the top three, what fed them
  local nm = function(id) return tostring(m.names and m.names[id] or id) end
  local top = {}
  for i = 1, math.min(3, #list) do top[#top + 1] = string.format("%s %.1f", nm(list[i].id), list[i].rating) end
  log(string.format("ratings from %s: MOTM %s; top %s%s%s", m.native and "the game" or tostring(m.mode or "the old formula"),
    nm(motm), table.concat(top, ", "), m.actSummary and ("; " .. m.actSummary) or "", m.logInfo and (" [" .. m.logInfo .. "]") or ""))
  -- once per match, each of the user's players' rating with the stats behind it
  local mine = tonumber(rawget(_G, "currentSelectedTeamID")) or m.home
  local dkey = table.concat({ tostring(m.date), tostring(m.home), tostring(m.away), tostring(m.hg), tostring(m.ag), tostring(m.mode) }, "|")
  if not m.native and CD.__detailKey ~= dkey then
    CD.__detailKey = dkey
    local row = {}
    for _, r in ipairs(m.players or {}) do row[r.id] = r end
    for _, x in ipairs(list) do
      local r = row[x.id]
      if r and r.team == mine and (r.mins or 0) > 0 then
        local ga = ((r.goals or 0) > 0 or (r.assists or 0) > 0) and string.format("%d goal(s) %d assist(s), ", r.goals or 0, r.assists or 0) or ""
        log(string.format("rating %s (%s, %d') %.1f: %s%s", nm(x.id), tostring(r.posName or r.line or "?"), r.mins or 0, x.rating, ga,
          CD.statLine(r.n, false)))
      end
    end
  end
  return out
end
-- The Player Performance screen (the post-match Performance tab, src/skins/PlayerPerformance.skin.js): both teams'
-- players with their match rating, goals and assists, and every stat behind the rating per tab next to the team's
-- totals. Built from liveRatings (rows with MatchRating's action counts, lineups, score) and the match's teams.
CD.PERF_TABS = { "Summary", "Possession", "Shooting", "Passing", "Defending", "Saving" }
-- a slot's place on a vertical pitch (x 0..1 left to right, y 0..1 from the attacking end to the own goal)
CD.PERF_PITCH = {
  GK = { 0.5, 0.93 }, SW = { 0.5, 0.80 }, LB = { 0.12, 0.70 }, LCB = { 0.33, 0.77 }, CB = { 0.5, 0.77 }, RCB = { 0.67, 0.77 },
  RB = { 0.88, 0.70 }, LWB = { 0.10, 0.56 }, RWB = { 0.90, 0.56 }, LDM = { 0.33, 0.61 }, CDM = { 0.5, 0.61 }, RDM = { 0.67, 0.61 },
  LM = { 0.12, 0.44 }, LCM = { 0.33, 0.48 }, CM = { 0.5, 0.48 }, RCM = { 0.67, 0.48 }, RM = { 0.88, 0.44 }, LAM = { 0.30, 0.34 },
  CAM = { 0.5, 0.34 }, RAM = { 0.70, 0.34 }, LW = { 0.15, 0.20 }, RW = { 0.85, 0.20 }, LF = { 0.33, 0.18 }, CF = { 0.5, 0.20 },
  RF = { 0.67, 0.18 }, LS = { 0.38, 0.11 }, ST = { 0.5, 0.11 }, RS = { 0.62, 0.11 },
}
--- Spots for the starters' dots on the pitch. The lineup names each starter's slot by its role only (a back four is RB,
--- CB, CB, LB and a 4-3-3 can be CDM, CDM, CM), so the role's spot alone would stack two centre-backs into one dot.
--- Players sharing a spot are spread across their line instead, in lineup order, which is the formation's slot order
--- (the stock Starting XI hands lineup[i] formation slot i; formations list every line right to left: RB before LB,
--- the right centre-back first). Nothing assumes a formation: whatever the lineup says is drawn, one dot per player.
--- @param slots string[]  the starters' slot names in lineup order
--- @return table          { [i] = { x, y } or false (a slot name with no spot) }
function CD.pitchLayout(slots)
  local pts, groups, order = {}, {}, {}
  for i = 1, #slots do
    local b = CD.PERF_PITCH[tostring(slots[i] or ""):upper()]
    if b then
      pts[i] = { b[1], b[2] }
      local key = string.format("%.3f:%.3f", b[1], b[2])
      if not groups[key] then groups[key] = {}; order[#order + 1] = key end
      local g = groups[key]; g[#g + 1] = i
    else
      pts[i] = false
    end
  end
  for _, key in ipairs(order) do
    local g = groups[key]
    local k = #g
    if k > 1 then
      -- two: about where LCB/RCB sit (0.35 / 0.65); three or more: evenly across the line
      local gap = k == 2 and 0.30 or math.min(0.22, 0.80 / (k - 1))
      for j, i in ipairs(g) do
        local x = pts[i][1] + ((k - 1) / 2 - (j - 1)) * gap   -- the first in slot order on the right
        pts[i][1] = math.max(0.06, math.min(0.94, x))
      end
    end
  end
  return pts
end
-- One player's (or a team's: counts summed) stats from MatchRating's action counts n and the scoresheet row x.
local function perfCounts(n, x)
  n = n or {}
  local function c(k) return math.floor((n[k] or 0) + 0.5) end
  local s = { goals = x.goals or 0, assists = x.assists or 0, yc = x.yc or 0, rc = x.rc or 0, mins = x.mins or 0, conc = x.conc or 0 }
  s.onT, s.offT = c("shot_on"), c("shot_off"); s.shots = s.onT + s.offT
  s.bigMiss, s.penMiss, s.penGoals = c("bigmiss"), c("pen_miss"), c("pen_goal")
  s.passOk = c("pass"); s.mispass = c("pass_bad") + c("through_bad") + c("cross_bad"); s.offsidePass = c("pass_offside")
  s.passes = s.passOk + s.mispass + s.offsidePass
  s.chances, s.bigChances, s.assist2 = c("keypass") + c("bigcreate"), c("bigcreate"), c("assist2")
  s.crossOk = c("cross"); s.crosses = s.crossOk + c("cross_bad"); s.through = c("through")
  s.dribbleOk = c("dribble"); s.dribbles = s.dribbleOk + c("dribble_bad"); s.box = c("box")
  s.tackleOk = c("tackle"); s.tackles = s.tackleOk + c("tackle_bad"); s.intercept, s.clear = c("intercept"), c("clear")
  s.aerialOk = c("header"); s.aerials = s.aerialOk + c("header_bad")
  s.fouls, s.penConceded, s.offsides = c("foul"), c("pen_conceded"), c("offside")
  s.errShot, s.errGoal = c("error_shot"), c("error_goal")
  s.won = s.tackleOk + s.intercept; s.lost = s.mispass + c("dribble_bad")
  s.saves, s.penSaves, s.claims = c("save"), c("pen_save"), c("claim") + c("claim_bad"); s.bigSaves = c("save_big") + s.penSaves
  return s
end
CD.perfCounts = perfCounts
-- A stat row value: the percentage a/b of the counts ("-" when b is 0).
local function pct(a, b) return function(s) if (s[b] or 0) <= 0 then return "-" end return tostring(math.floor(100 * s[a] / s[b] + 0.5)) end end
local D = true   -- needs the native match log (the scoresheet alone does not have it)
-- The stat rows of each tab: { label, key of the counts | function(counts) -> text, D }. D marks the rows only the
-- native match log has ("-" for a match rated from the scoresheet).
CD.PERF_ROWS = {
  { { "Goals", "goals" }, { "Assists", "assists" }, { "Shots", "shots", D }, { "Shot Accuracy (%)", pct("onT", "shots"), D },
    { "Passes", "passes", D }, { "Pass Accuracy (%)", pct("passOk", "passes"), D }, { "Dribbles", "dribbles", D },
    { "Dribble Success Rate (%)", pct("dribbleOk", "dribbles"), D }, { "Tackles", "tackles", D },
    { "Tackle Success Rate (%)", pct("tackleOk", "tackles"), D }, { "Offsides", "offsides", D }, { "Fouls Committed", "fouls", D },
    { "Minutes Played", "mins" }, { "Possession Won", "won", D }, { "Possession Lost", "lost", D } },
  { { "Dribbles", "dribbles", D }, { "Dribbles Won", "dribbleOk", D }, { "Dribble Success Rate (%)", pct("dribbleOk", "dribbles"), D },
    { "Touches Into The Box", "box", D }, { "Possession Won", "won", D }, { "Possession Lost", "lost", D },
    { "Misplaced Passes", "mispass", D }, { "Errors Leading To A Shot", "errShot", D }, { "Errors Leading To A Goal", "errGoal", D } },
  { { "Goals", "goals" }, { "Penalty Goals", "penGoals", D }, { "Shots", "shots", D }, { "Shots On Target", "onT", D },
    { "Shots Off Target", "offT", D }, { "Shot Accuracy (%)", pct("onT", "shots"), D }, { "Big Chances Missed", "bigMiss", D },
    { "Penalties Missed", "penMiss", D } },
  { { "Passes", "passes", D }, { "Passes Completed", "passOk", D }, { "Pass Accuracy (%)", pct("passOk", "passes"), D },
    { "Chances Created", "chances", D }, { "Big Chances Created", "bigChances", D }, { "Assists", "assists" },
    { "Second Assists", "assist2", D }, { "Crosses", "crosses", D }, { "Crosses Completed", "crossOk", D },
    { "Through Balls Completed", "through", D }, { "Passes Into Offside", "offsidePass", D } },
  { { "Tackles", "tackles", D }, { "Tackles Won", "tackleOk", D }, { "Tackle Success Rate (%)", pct("tackleOk", "tackles"), D },
    { "Interceptions", "intercept", D }, { "Clearances", "clear", D }, { "Aerial Duels", "aerials", D },
    { "Aerial Duels Won", "aerialOk", D }, { "Fouls Committed", "fouls", D }, { "Penalties Conceded", "penConceded", D },
    { "Yellow Cards", "yc" }, { "Red Cards", "rc" } },
  { { "Saves", "saves" }, { "Big Saves", "bigSaves", D }, { "Penalties Saved", "penSaves", D },
    { "Punches And Rushes", "claims", D }, { "Goals Conceded", "conc" },
    { "Clean Sheet", function(s) if s.cleanSheet == nil then return "-" end return s.cleanSheet and "Yes" or "No" end } },
}
-- "First Last name" -> first, last; a single word is the last name.
local function splitName(nm)
  nm = tostring(nm or "")
  local first, last = nm:match("^(%S+)%s+(.+)$")
  if not first then return "", nm end
  return first, last
end
--- The Player Performance data of a match.
--- @param r table      liveRatings' result
--- @param teams table  { [1] = home team row, [2] = away team row } (teamName, teamNameAbbr)
--- @return table?  P = { sides = { [1] = home, [2] = away }, mine = index of the user's side, detailed (the native log
---                   fed the ratings), native, len, mode, now }
---                 side = { id, name, abbr, gf, ga, players, totals (perfCounts + cleanSheet), pitch (pitchLayout) }
---                 player = { id, name, first, last, pos ("SUB" for substitutes), slot (where he played), ovr, rating,
---                   g, a, mins, played, motm, s (perfCounts), starter, dot (index into side.pitch) }
function CD.performance(r, teams)
  if type(r) ~= "table" or type(r.rows) ~= "table" then return nil end
  teams = type(teams) == "table" and teams or {}
  local P = { sides = {}, detailed = r.mode == "log", native = r.native, len = r.len or 90, mode = r.mode, now = r.now }
  local mine = tonumber(rawget(_G, "currentSelectedTeamID"))
  for k, teamId in ipairs({ r.home, r.away }) do
    local t = teams[k] or {}
    local lu = type(r.lineups) == "table" and r.lineups[teamId] or {}
    local side = { id = teamId, name = tostring(t.teamName or t.teamNameAbbr or teamId or ""), abbr = tostring(t.teamNameAbbr or t.teamName or ""),
                   players = {}, gf = (k == 1 and r.hg or r.ag) or 0, ga = (k == 1 and r.ag or r.hg) or 0 }
    local n, starters, subs, unused = {}, {}, {}, {}
    for i, lr in ipairs(lu) do
      local id = idOf(lr)
      if id then
        local row = r.rows[id] or {}
        local first, last = splitName(lr.playerName)
        local played = (row.mins or 0) > 0 or (i <= 11 and r.rows[id] ~= nil)
        local p = { id = id, name = tostring(lr.playerName or id), first = first, last = last, slot = tostring(lr.position or row.posName or ""):upper(),
                    ovr = tonumber(CD.ovrOf(id, lr.overallRating or lr.rating or lr.ovr)), rating = played and (tonumber(r[id]) or tonumber(row.rating)) or nil, g = row.goals or 0,
                    a = row.assists or 0, mins = row.mins or 0, played = played, motm = r.motm == id, on = row.on, off = row.off,
                    s = perfCounts(row.n, row), starter = i <= 11 }
        p.pos = p.starter and p.slot or "SUB"
        if p.starter then starters[#starters + 1] = p elseif played then subs[#subs + 1] = p else unused[#unused + 1] = p end
        if played then for kk, v in pairs(row.n or {}) do n[kk] = (n[kk] or 0) + v end end
      end
    end
    -- a substitute plays where the man he replaced did (the starter who went off when he came on)
    for _, sp in ipairs(subs) do
      for _, st in ipairs(starters) do
        if not st.replaced and st.off and sp.on and math.abs(st.off - sp.on) < 0.5 then st.replaced = sp; sp.slot = st.slot; break end
      end
    end
    for i, p in ipairs(starters) do p.dot = i end
    local slots = {}
    for i, p in ipairs(starters) do slots[i] = p.slot end
    side.pitch = CD.pitchLayout(slots)   -- one spot per starter (dot i)
    for _, sp in ipairs(subs) do for _, st in ipairs(starters) do if st.replaced == sp then sp.dot = st.dot end end end
    for _, grp in ipairs({ starters, subs, unused }) do for _, p in ipairs(grp) do side.players[#side.players + 1] = p end end
    local tot = { goals = 0, assists = 0, yc = 0, rc = 0 }
    for _, p in ipairs(side.players) do
      local row = r.rows[p.id] or {}
      tot.goals = tot.goals + (row.goals or 0); tot.assists = tot.assists + (row.assists or 0)
      tot.yc = tot.yc + (row.yc or 0); tot.rc = tot.rc + (row.rc or 0)
    end
    tot.mins, tot.conc = math.floor((P.now or P.len) + 0.5), side.ga
    side.totals = perfCounts(n, tot)
    side.totals.cleanSheet = side.ga == 0
    for _, p in ipairs(side.players) do if p.played then p.s.cleanSheet = (p.s.conc == 0 and p.mins >= 60) end end
    P.sides[k] = side
    if mine and teamId == mine then P.mine = k end
  end
  P.mine = P.mine or 1
  return P
end
--- The stat rows of one tab of the Player Performance screen: { { label, mine, team } ... } for the player p and the
--- team's totals. "-" stands for what only the native match log has, in a match rated from the scoresheet.
--- @param P table      performance()'s result
--- @param side number  1 home, 2 away
--- @param p table?     the player (nil: his column shows "-")
--- @param tab number   index into PERF_TABS
function CD.performanceStats(P, side, p, tab)
  local rows = CD.PERF_ROWS[tab] or CD.PERF_ROWS[1]
  local out = {}
  local S = P.sides[side]
  for _, d in ipairs(rows) do
    local function val(s, isPlayer)
      if d[3] and not P.detailed then return "-" end
      if isPlayer and (not p or not p.played) then return "-" end
      if type(d[2]) == "function" then return d[2](s) end
      return tostring(s[d[2]] or 0)
    end
    out[#out + 1] = { label = d[1], mine = val(p and p.s or {}, true), team = val(S.totals, false) }
  end
  return out
end
-- The colour (hex string) of a match rating: green from 8, lime from 7, amber from 6, red below; faded without one.
function CD.perfRatingColor(r)
  if not r then return "#FFFFFF73" end
  if r >= 8 then return "#3DDC84" elseif r >= 7 then return "#A6E35C" elseif r >= 6 then return "#F2A43A" end
  return "#F0504F"
end

--- Adds the assists of the user's match (the engine's own counters, m.players[].assists) to sessionVars
--- "PlayerAssists" = { [leagueID] = { [playerID] = n } }, under the competition of the match
--- (currentLigaData.leagueID, where the match HUD files the goals). A match counts once however often its result is
--- recorded: the fixture in MatchData carries the mark (saved with it); a match without a fixture entry is told apart
--- by its teams, day and score.
--- @param m table  userMatch's result
--- @return number  the assists added
function CD.countUserAssists(m)
  local sv = svars()
  if not (sv and sv.get and sv.set) or type(m) ~= "table" or type(m.players) ~= "table" then return 0 end
  local cld = rawget(_G, "currentLigaData")
  local league = tonumber(type(cld) == "table" and cld.leagueID or nil) or tonumber(sv.get("currentUserLeagueID"))
  if not league then return 0 end
  local fixture = type(cld) == "table" and (sv.get("MatchData") or {})[cld.round] or nil
  if type(fixture) == "table" and fixture.homeID == m.home and fixture.awayID == m.away then
    if fixture.assistsCounted then return 0 end
    fixture.assistsCounted = true
  else
    local key = table.concat({ tostring(m.home), tostring(m.away), tostring(careerDay()), tostring(m.hg), tostring(m.ag) }, ":")
    if G.assistsKey == key then return 0 end
    G.assistsKey = key
  end
  local all = sv.get("PlayerAssists") or {}
  local counts, n = all[league] or {}, 0
  for _, r in ipairs(m.players) do
    local id, a = tonumber(r.id), tonumber(r.assists) or 0
    if id and a > 0 then counts[id] = (counts[id] or 0) + a; n = n + a end
  end
  if n > 0 then all[league] = counts; sv.set("PlayerAssists", all) end
  return n
end

--- Records the user's match with PlayerDev once it is over (the match-day result in GameMenu): ratings, man of the
--- match, form and appearances. It also stops the native stats sampler. Nothing is recorded outside a career
--- (G.active is false: a quick match, a tournament after leaving the career) or when the user's club did not play.
--- @param svcs table  see userMatch
--- @param hg number?  the final score, when known
--- @param ag number?
--- @return table?, number?  { [playerId] = rating }, the man of the match's id
function CD.recordUserMatch(svcs, hg, ag)
  local f = F16()
  if f then pcall(f.Cmd, "match:disarm") end   -- the sampler stops; the match's log stays readable
  if not G.active then return nil end   -- not a career match (quick match, tournament after leaving the career)
  local m = CD.userMatch(svcs, hg, ag)
  if not m then log("user match: no lineups/events"); return nil end
  local mine = tonumber(rawget(_G, "currentSelectedTeamID"))
  if mine and m.home ~= mine and m.away ~= mine then return nil end
  local ratings, motm = CD.recordMatch(m.home, m.away, m.hg, m.ag, m.players, false, m.motm)
  pcall(CD.countUserAssists, m)
  log(string.format("user match %s-%s %d:%d recorded (%d players, motm %s, %s)", tostring(m.home), tostring(m.away), m.hg, m.ag,
    #m.players, tostring(motm), m.native and "the game's ratings" or ("ratings from " .. tostring(m.mode or "the old formula") ..
    (m.logInfo and (": " .. m.logInfo) or ""))))
  return ratings, motm
end

-- Weight of each position group in the draw of a goal's assister (see recordSimMatch).
local AST = { GK = 0.05, CB = 0.3, FB = 1.0, WB = 1.2, CDM = 0.8, CM = 2.0, CAM = 3.2, WM = 2.6, CF = 2.2, W = 2.8, ST = 1.6 }
-- Lineup slot name -> position group of AST.
local POSN = { GK = "GK", CB = "CB", LCB = "CB", RCB = "CB", SW = "CB", LB = "FB", RB = "FB", LWB = "WB", RWB = "WB",
  CDM = "CDM", LDM = "CDM", RDM = "CDM", CM = "CM", LCM = "CM", RCM = "CM", CAM = "CAM", LAM = "CAM", RAM = "CAM",
  LM = "WM", RM = "WM", CF = "CF", LF = "CF", RF = "CF", LW = "W", RW = "W", ST = "ST", LS = "ST", RS = "ST" }
--- Records a simulated match (the hook in MatchSimulator): builds the players' minutes, goals, assists and cards from
--- what the simulator generated and passes the rated rows to recordMatch. The assister of a goal is the simulator's
--- (the one it counted into PlayerAssists); a scorer entry without that decision (a simulator that makes none) gets
--- a team-mate drawn by position weight (AST) with a generator seeded from the date and the clubs.
--- @param home number         club ids
--- @param away number
--- @param hg number           the score
--- @param ag number
--- @param hSq table           the squads as played: rows with CARD_ID and position, the first 11 are the XI
--- @param aSq table
--- @param hSc table           the scorers per side: { { name, id, assisted, assistID } ... }
--- @param aSc table
--- @param events table?       the generated events with minutes: eventType 4 substitution (playerID in, playerID2
---                            out), 5 yellow, 6 second yellow, 9 goal; isHome tells the side
--- @param hRed table?         the pre-decided straight red per side:
---                            { player = <squad row>, position, minute, isDouble }
--- @param aRed table?
function CD.recordSimMatch(home, away, hg, ag, hSq, aSq, hSc, aSc, events, hRed, aRed)
  local PD = PDm()
  if not PD or not G.active then return end
  local rows, byId = {}, {}
  local function add(id, team, mins)
    id = tonumber(id); if not id then return nil end
    if not byId[id] then byId[id] = { id = id, team = team, mins = mins, goals = 0, assists = 0, yc = 0, rc = 0, on = 0, off = 90 }; rows[#rows + 1] = byId[id] end
    return byId[id]
  end
  local xi = {}
  for _, side in ipairs({ { home, hSq }, { away, aSq } }) do
    xi[side[1]] = {}
    for i = 1, math.min(11, type(side[2]) == "table" and #side[2] or 0) do
      local r = side[2][i]
      local x = r and add(r.CARD_ID, side[1], 90)
      if x then x.grp = POSN[tostring(r.position or ""):upper()]; x.posName = r.position; xi[side[1]][#xi[side[1]] + 1] = x end
    end
  end
  local actions = {}
  for _, ev in ipairs(type(events) == "table" and events or {}) do
    local team = ev.isHome and home or away
    local t = tonumber(ev.minute) or 45
    if ev.eventType == 4 and ev.playerID then
      local x = add(ev.playerID, team, 25); if x then x.on = t; x.off = 90 end
      local o = byId[tonumber(ev.playerID2)]; if o then o.off = math.min(o.off, t) end
    elseif ev.eventType == 5 and ev.playerID then actions[#actions + 1] = { t = t, team = team, pid = tonumber(ev.playerID), k = "yellow" }
    elseif ev.eventType == 6 and ev.playerID then actions[#actions + 1] = { t = t, team = team, pid = tonumber(ev.playerID), k = "red", second = true }
    end
  end
  local seed = (careerDay() or 0) * 7 + (tonumber(home) or 0) * 13 + (tonumber(away) or 0)
  local function rnd() seed = (seed * 16807) % 2147483647; return seed / 2147483647 end
  -- goals: the k-th scorer of a side is that side's k-th goal event (MatchSimulator inserts them in order); assists:
  -- the simulator's, else a team-mate by position
  for _, side in ipairs({ { home, hSc, true }, { away, aSc, false } }) do
    local mins = {}
    for _, ev in ipairs(type(events) == "table" and events or {}) do
      if ev.eventType == 9 and (ev.isHome == true) == side[3] then mins[#mins + 1] = tonumber(ev.minute) end
    end
    local list = type(side[2]) == "table" and side[2] or {}
    for k, sc in ipairs(list) do
      local r = add(sc.id, side[1], 90)
      local g = { t = mins[k] or (k * 90 / (#list + 1)), team = side[1], pid = r and r.id, k = "goal" }
      if r then
        r.goals = r.goals + 1
        if sc.assisted ~= nil then
          -- the simulator settled it (and counted it into PlayerAssists): the stored stat and the development agree
          local a = sc.assisted and (byId[tonumber(sc.assistID)] or add(sc.assistID, side[1], 90)) or nil
          if a and a ~= r then a.assists = a.assists + 1; g.assist = a.id end
        elseif rnd() < 0.75 then
          local pool, tot = {}, 0
          for _, x in ipairs(xi[side[1]]) do
            if x ~= r then
              local p = PD.get(x.id)
              local grp = p and PD.GROUP[p.pos] or x.grp or "CM"
              local w = AST[grp] or 1; pool[#pool + 1] = { x, w }; tot = tot + w
            end
          end
          local pick = rnd() * tot
          for _, it in ipairs(pool) do pick = pick - it[2]; if pick <= 0 then it[1].assists = it[1].assists + 1; g.assist = it[1].id; break end end
        end
      end
      actions[#actions + 1] = g
    end
  end
  for _, red in ipairs({ hRed, aRed }) do
    -- MatchSimulator's pre-decided red: { player = <squad row>, position, minute, isDouble }
    if type(red) == "table" then
      local rid = tonumber(red.playerID or red.id or (type(red.player) == "table" and red.player.CARD_ID) or -1)
      local x = byId[rid]
      if x then
        x.rc = 1; x.mins = tonumber(red.minute) or x.mins
        actions[#actions + 1] = { t = tonumber(red.minute) or 60, team = x.team, pid = x.id, k = "red" }
      end
    end
  end
  for _, x in ipairs(rows) do x.mins = math.max(0, math.floor((x.off or 90) - (x.on or 0) + 0.5)) end
  local rated = rateRows({ date = careerDay() or 0, seed = PD.state and PD.state.seed, home = home, away = away, mode = "sim",
                           players = rows, actions = actions })
  CD.recordMatch(home, away, hg or 0, ag or 0, rated or rows, true)
end

--- Records a rated match with PlayerDev (form, appearances, goals, assists, man of the match). The user's match is
--- also left in sessionVars "LastMatchRatings" = { ratings, motm, home, away }.
--- @param rows table      { { id, team, mins, goals, assists, yc, rc, rating? } }; a row's own rating (the game's or
---                        MatchRating's) is used as it is, otherwise PlayerDev rates the row
--- @param sim boolean     true for a simulated match (LastMatchRatings is left alone)
--- @param motmId number?  the game's man of the match, when it named one
--- @return table?, number?  { [playerId] = rating }, the man of the match's id
function CD.recordMatch(home, away, hg, ag, rows, sim, motmId)
  local PD = PDm()
  if not PD then return nil end
  local ratings, motm = PD.recordMatch({ date = careerDay() or 0, home = home, away = away, hg = hg, ag = ag, sim = sim, players = rows, motm = motmId })
  if not sim then
    local sv = svars()
    if sv and sv.set then sv.set("LastMatchRatings", { ratings = ratings, motm = motm, home = home, away = away }) end
  end
  -- Player Career: the user's own player's stats and the manager's trust
  do local PRO = rawget(_G, "PrismPro"); if PRO and PRO.onMatch then pcall(PRO.onMatch, home, away, hg, ag, rows, ratings, motm, sim) end end
  return ratings, motm
end

------------------------------------------------------------------------ save
--- The development state for the career save (Serializer stores it as playerDev); nil without PlayerDev.
function CD.serialize()
  local PD = PDm()
  if not PD then return nil end
  return PD.serialize()
end
--- Loads a saved development state (PlayerDev.deserialize) and forgets the read queue. A save that had development data
--- that could not be read leaves the state empty and sets PRISM_SAVE_KEEPALL.
--- @param t table?  the saved table
--- @return boolean  true when the state was read
function CD.deserialize(t)
  local PD = PDm()
  if not PD then return false end
  local ok = PD.deserialize(t)
  G.queue, G.queued = {}, {}
  G.appliedCareer = nil
  if type(t) == "table" and not ok then
    -- the save had development data and it did not load: keep every backup of the career store this session, so
    -- saving the empty state can never prune the generations that still hold it
    rawset(_G, "PRISM_SAVE_KEEPALL", true)
    log("career development in the save could not be read: this session keeps every save backup")
  end
  log("career development loaded: " .. CD.count() .. " players")
  return ok
end
--- Starts a new development state from the database. seed (default: from the clock) drives the random growth.
function CD.newCareer(seed)
  local PD = PDm()
  if not PD then return end
  PD.reset(tonumber(seed) or math.floor((os.time and os.time() or 1) % 2147483646) + 1)
  G.queue, G.queued, G.appliedCareer = {}, {}, nil
  log("new career: development starts from the database")
end

rawset(_G, "CareerDev", CD)
return CD
