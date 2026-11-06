-- PrismYouth - retirements, a youth pool the AI clubs draw from when they need players, and the user's youth academy.
--
-- Bodies. The game cannot add a player to its database (there is no insert), and live database writes are switched off
-- (a live write crashes the game). A youth player is therefore a real database row the career never shows: a player of
-- a club in a league outside the career (PrismYouthHosts.lua, built from the user's database by tools/youth_hosts.py),
-- and later a player who retired at least RECYCLE_AFTER seasons ago. His name, face, height and nationality are that
-- row's - the same on the squad screens and in a 3D match. Everything the career decides is generated here: his date of
-- birth (15 to 18), potential, overall and the 33 attributes behind it. Real matches get those attributes through the
-- engine's match override table (CareerDev.matchOverrides), squad screens through the career's squad rows.
--
-- Where a youth plays. Youths behave like the database's own players of their club (y.club): PrismYouth puts their rows
-- into that club's squad whenever the career caches it (getCachedTeamPlayers, LoadSave before the roster is restored),
-- and takes rows of youths that belong elsewhere out. Every later move - a sale, a loan, a release - is an ordinary
-- SquadState roster move, saved and restored like any other.
--
-- Kinds (y.k): "C" in a club's squad, "P" in the pool (no club yet), "A" in the user's academy (not in the first-team
-- squad until promoted).
--
-- Season end (SeasonInit, Y.seasonEnd): who retires (by age and overall; keepers retire GK_SHIFT years later), the
-- youths' yearly development (CareerDev develops the ones it tracks month by month), academy leavers, then each AI
-- club's intake (its retired players replaced, a squad below MIN_SQUAD topped up, short lines first) from the pool and
-- new youths, then the pool and the academy refilled. During the season (Date, Y.onDay): a club with a match today and
-- fewer than FIT_MIN fit players, or no fit keeper, gets youths from the pool (the user: from the academy).
--
-- Cost: new youths come from the host list in the database's club order, so a batch of a thousand opens a few dozen of
-- the clubs they come from (one engine lineup call each) to read their names. Everything else is table work.
--
-- Hooks (src/patches/Youth.patch.js; every one is guarded, the stock code runs when this module is missing):
--   Y.bind          the hub binds (MatchSelect): hands over sessionVars, creates academy and pool for a new career
--   Y.step          the hub's update: reads birthdates a few per frame, opens the season end's host clubs in spring
--   Y.seasonEnd     SeasonInit:initSeason          Y.onDay   Date:advanceDate
--   Y.inject        getCachedTeamPlayers (a club cached later gets its youths)   Y.injectAll   LoadSave
--   Y.serialize     Serializer (the save's `youth` field)      Y.decode   decodes it (Y.state does so on first use)
--   Y.clubOf        SquadState.clubOf              Y.openAcademy   the hub's Youth Academy card
--   Y.track / Y.pdLike / Y.birthOf / Y.isYouth   CareerDev (development tracking, match overrides, birthdates)
--
-- State: sessionVars "_prismYouth" (saved with the career as compact strings by Y.serialize):
--   { v, seed, season (season ends done), hc (cursor into the host list), last (summary of the latest season end),
--     reg = { [playerId] = y },    the youths
--     ret = { [playerId] = { s = season he retired in (-9999: unusable body), p = position code, o = origin club } },
--     spill = { { id, club, pos } ... },    host bodies skipped by earlier batches, used first by the next
--     bt = { [clubId] = base tier } }       the level a club's youths are made for (see baseTier)
-- A youth y: { b birth (FIFA day), p position code (0..27), t potential, o overall, s seed (his attribute noise),
--   c season created, k kind, club (kind "C" only), org (the host's club in the database), nm name, nat nationality id,
--   js jersey number, ps position name }.
local Y = {}
local floor, max, min = math.floor, math.max, math.min
local function clamp(v, a, b) if v < a then return a elseif v > b then return b end return v end

-- Tuning. ACADEMY: academy size; ACADEMY_AGE / POOL_AGE / CLUB_AGE: age range of new academy / pool / club youths;
-- ACADEMY_LEAVE: age at which an academy player is promoted or released to the pool; POOL: pool size; POOL_AGE_OUT: age
-- at which a pool youth goes back to the retired bodies; MIN_SQUAD / MAX_SQUAD: an AI club's intake range; FIT_MIN: fit
-- players a club needs on match day; USER_SQUAD_MAX: promotions at the season end stop at this squad size;
-- RECYCLE_AFTER: seasons before a retired player's row can become a youth; LINE_MIN: minimum squad players per line;
-- ACADEMY_MIX: wanted academy players per line.
Y.CFG = {
  ACADEMY = 20, ACADEMY_AGE = { 15, 17 }, ACADEMY_LEAVE = 19,
  POOL = 120, POOL_AGE = { 16, 18 }, POOL_AGE_OUT = 21,
  CLUB_AGE = { 16, 18 },
  MIN_SQUAD = 22, MAX_SQUAD = 30, FIT_MIN = 16, USER_SQUAD_MAX = 32,
  RECYCLE_AFTER = 5,
  LINE_MIN = { GK = 3, DEF = 7, MID = 7, ATT = 4 },
  ACADEMY_MIX = { GK = 2, DEF = 6, MID = 7, ATT = 5 },
  -- chance to retire at a season's end, by age (outfield; keepers GK_SHIFT years later); see Y.retireChance
  RETIRE = { { 31, 0.0 }, { 32, 0.04 }, { 33, 0.10 }, { 34, 0.22 }, { 35, 0.38 }, { 36, 0.55 }, { 37, 0.72 }, { 38, 0.86 }, { 39, 0.97 } },
  GK_SHIFT = 2,
}
local CFG = Y.CFG

------------------------------------------------------------------------ helpers
-- Shared module state in the global PRISM_YOUTH (every career screen has its own copy of this file): the message log,
-- the sessionVars handed over by Y.bind (G.sv), and caches (youth-by-club index, host list, attribute cache, the
-- birthdate warm-up queue and the club prefetch list).
local G = rawget(_G, "PRISM_YOUTH")
if type(G) ~= "table" then G = { log = {} }; rawset(_G, "PRISM_YOUTH", G) end
Y.G = G
-- The career's sessionVars: handed over by Y.bind, else the global CAREER_SESSION_VARS.
local function sv() return G.sv or rawget(_G, "CAREER_SESSION_VARS") end
-- Keeps the message in G.log (the last 40) and writes it to the native log as "log:youth: ...".
local function log(msg)
  G.log[#G.log + 1] = msg
  if #G.log > 40 then table.remove(G.log, 1) end
  local f = rawget(_G, "F16_SVC")
  if f and f.Cmd then pcall(f.Cmd, "log:youth: " .. tostring(msg)) end
end
Y.log = log

-- Seeded Park-Miller generator (as in PlayerDev): returns a function giving floats in (0, 1).
local function rng(seed)
  local s = floor(seed) % 2147483646 + 1
  for _ = 1, 4 do s = (s * 16807) % 2147483647 end
  return function() s = (s * 16807) % 2147483647; return s / 2147483647 end
end
-- Mixes any number of numbers into one seed for rng.
local function hash(...)
  local h = 2166136
  for i = 1, select("#", ...) do h = (h * 31 + floor(tonumber((select(i, ...))) or 0)) % 2147483629 end
  return h
end
-- A standard normal sample from two draws of rng function `r` (Box-Muller).
local function gauss(r) local u = max(r(), 1e-9); return math.sqrt(-2 * math.log(u)) * math.cos(6.283185307 * r()) end

-- FIFA day numbers (days since 1582-10-14), what the database's birthdates and PlayerDev use
local function civil(y, m, d)
  y = (m <= 2) and (y - 1) or y
  local era = floor(y / 400)
  local yoe = y - era * 400
  local doy = floor((153 * (m + (m > 2 and -3 or 9)) + 2) / 5) + d - 1
  return era * 146097 + yoe * 365 + floor(yoe / 4) - floor(yoe / 100) + doy - 719468
end
local FIFA0 = civil(1582, 10, 14)
local function dayOf(y, m, d) return civil(y, m, d) - FIFA0 end
local function years(from, to) return (to - from) / 365.2425 end
Y.dayOf = dayOf
--- Today as a FIFA day number, plus year, month and day. The career calendar is "DD/MM/YY"; the two-digit year is
--- resolved against CAREER_FULL_YEAR. Returns nil when the date is unknown.
local function today()
  local s = sv()
  local ds = tostring(rawget(_G, "GLOBAL_DATE_PLACEHOLDER") or (s and s.get and s.get("GLOBAL_DATE_PLACEHOLDER")) or "")
  local d, m, yy = ds:match("^(%d%d)/(%d%d)/(%d%d)$")
  if not d then return nil end
  yy = tonumber(yy)
  local full = tonumber(rawget(_G, "CAREER_FULL_YEAR")) or (s and s.get and tonumber((s.get("_careerFullYear")))) or (2000 + yy)
  local y = full - full % 100 + yy
  if y < full - 50 then y = y + 100 elseif y > full + 50 then y = y - 100 end
  return dayOf(y, tonumber(m), tonumber(d)), y, tonumber(m), tonumber(d)
end
Y.today = today

-- Position code (0..27) <-> name; lineOf maps a code to GK / DEF / MID / ATT (default CM); rowPos reads the code of a
-- squad row (the goalkeeper flag, else the position name).
local POSNAME = { [0] = "GK", "SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB", "RDM", "CDM", "LDM", "RM", "RCM", "CM",
  "LCM", "LM", "RAM", "CAM", "LAM", "RF", "CF", "LF", "RW", "RS", "ST", "LS", "LW" }
local POSCODE = {}
for c = 0, 27 do POSCODE[POSNAME[c]] = c end
--- The line (GK / DEF / MID / ATT) of a position code.
local function lineOf(pos) pos = tonumber(pos) or 14; if pos == 0 then return "GK" elseif pos <= 8 then return "DEF" elseif pos <= 19 then return "MID" end return "ATT" end
Y.lineOf = lineOf
local function rowPos(row)
  if type(row) ~= "table" then return 14 end
  if row.isGoalie == true then return 0 end
  return POSCODE[tostring(row.position or "")] or 14
end
local LINES = { "GK", "DEF", "MID", "ATT" }

-- Lazy handles: PlayerDev, SquadState (global PRISM_SQUAD_STATE) and the career's cached squads (sessionVars
-- TeamCachedData: { [teamID] = { players = { rows }, league } }).
local function PDm() return rawget(_G, "PlayerDev") end
local function SSm() return rawget(_G, "PRISM_SQUAD_STATE") end
local function cacheOf() local s = sv(); return s and s.get and s.get("TeamCachedData") or nil end

------------------------------------------------------------------------ state
local KEY = "_prismYouth"   -- the sessionVars key of the state (see the header)
local function newState(seed)
  return { v = 1, seed = floor(tonumber(seed) or 1), season = 0, hc = 1, reg = {}, ret = {}, spill = {}, last = nil, bt = {} }
end
--- The youth state from sessionVars, or nil outside a career or before one exists. A loaded save hands it over as
--- { raw = <saved table> } (LoadSave); it is decoded here on first use.
function Y.state()
  local s = sv()
  if not (s and s.get) then return nil end
  local st = s.get(KEY)
  if type(st) == "table" and st.raw ~= nil then   -- a loaded save's youth (LoadSave hands it over raw)
    st = st.raw and Y.decode(st.raw) or nil
    s.set(KEY, st or false)
    G.index = nil
  end
  if type(st) == "table" and type(st.reg) == "table" then
    if G.indexOf ~= st then G.index = nil end
    return st
  end
  return nil
end
-- Youths by club (kind "C"): { [club] = { [id] = y } }, rebuilt when the state changes hands.
local function index(st)
  if G.index and G.indexOf == st then return G.index end
  local by = {}
  for id, y in pairs(st.reg) do
    if y.k == "C" and y.club then local t = by[y.club]; if not t then t = {}; by[y.club] = t end; t[id] = y end
  end
  G.index, G.indexOf = by, st
  return by
end
-- Moves a youth to `club` (nil = no club), keeping the index current.
local function setClub(st, id, y, club)
  local by = index(st)
  if y.club and by[y.club] then by[y.club][id] = nil end
  y.club = club
  if y.k == "C" and club then local t = by[club]; if not t then t = {}; by[club] = t end; t[id] = y end
end

--- Whether `id` is a generated youth.
function Y.isYouth(id) local st = Y.state(); return st ~= nil and st.reg[tonumber(id) or -1] ~= nil end
--- The youth record of `id` (see the header), or nil.
function Y.get(id) local st = Y.state(); return st and st.reg[tonumber(id) or -1] or nil end
--- A youth's birth as a FIFA day number, or nil for a database player.
function Y.birthOf(id) local y = Y.get(id); return y and y.b or nil end
--- The youth's club when the roster has no entry for him (SquadState.clubOf asks); nil unless he is in a club squad.
function Y.clubOf(id) local y = Y.get(id); return y and y.k == "C" and y.club or nil end
--- A youth's current overall: the developed one when CareerDev tracks him, else the generated one. nil for a non-youth.
function Y.ovrOf(id, y)
  y = y or Y.get(id)
  if not y then return nil end
  local PD = PDm()
  local p = PD and PD.get and PD.get(tonumber(id))
  if p and p.ovr then return p.ovr end
  return y.o
end

------------------------------------------------------------------------ attributes
--- The 33 attributes (PlayerDev.ATTRS order, each 5..99) of youth `y` at overall `ovr` (default y.o): his position's
--- profile (PlayerDev's formula weights: what counts for the position is high, the rest lower, keeper skills only for
--- keepers) with his own noise, shifted by one common amount (found by bisection) until the game's overall formula
--- gives exactly `ovr`. Deterministic per youth (his seed). nil when PlayerDev is missing.
function Y.attrsAt(y, ovr)
  local PD = PDm()
  if not PD or not PD.ATTRS or not PD.W then return nil end
  ovr = ovr or y.o
  local grp = PD.GROUP[y.p] or "ST"
  local w = PD.W[grp] or {}
  local gk = grp == "GK"
  local r = rng(y.s or 1)
  local raw = {}
  for i, n in ipairs(PD.ATTRS) do
    local isGk = n:sub(1, 2) == "gk"
    local wi = w[n] or 0
    local base
    if gk then base = isGk and 0 or -24
    elseif isGk then base = -50
    elseif wi >= 10 then base = 3
    elseif wi > 0 then base = -1
    else base = -14 end
    raw[i] = base + floor((r() * 2 - 1) * 8 + 0.5)
  end
  -- The overall at shift k without building the attribute table (PlayerDev.formulaArr's sum; youths have reputation 1,
  -- so no reputation bonus): only the final shift allocates.
  local wa = PD.WA and PD.WA[grp]
  local function ovrAt(k)
    if not wa then
      local a = {}
      for i = 1, #raw do a[i] = clamp(raw[i] + k, 5, 99) end
      return PD.formulaArr(a, y.p, 1)
    end
    local s = 0
    for i = 1, #raw do local wi = wa[i]; if wi ~= 0 then s = s + wi * clamp(raw[i] + k, 5, 99) end end
    return clamp(floor((s + 50) / 100), 1, 99)
  end
  local lo, hi = -60, 99
  for _ = 1, 20 do
    if hi - lo <= 1 then break end
    local mid = floor((lo + hi) / 2)
    if ovrAt(mid) >= ovr then hi = mid else lo = mid end
  end
  local a = {}
  for i = 1, #raw do a[i] = clamp(raw[i] + hi, 5, 99) end
  return a
end
--- A youth's attributes now (array in PlayerDev.ATTRS order): CareerDev's developed ones when it tracks him, else his
--- profile at his overall (cached per seed / overall / position).
function Y.attrsOf(id, y)
  y = y or Y.get(id)
  if not y then return nil end
  local PD = PDm()
  local p = PD and PD.get and PD.get(tonumber(id))
  if p and p.a then return p.a end
  G.ac = G.ac or {}
  local c = G.ac[id]
  if c and c.s == y.s and c.o == y.o and c.p == y.p then return c.a end
  local a = Y.attrsAt(y)
  G.ac[id] = { s = y.s, o = y.o, p = y.p, a = a }
  return a
end
-- The card's six faces from the attributes: labels and the attribute names behind each face (keepers have their own
-- six); FACE_IX holds the index lists into PlayerDev.ATTRS, built once.
local FACE_LABELS = { [true] = { "DIV", "HAN", "KIC", "REF", "SPD", "POS" }, [false] = { "PAC", "SHO", "PAS", "DRI", "DEF", "PHY" } }
local FACE_SPEC = {
  [true] = { { "gkDiving" }, { "gkHandling" }, { "gkKicking" }, { "gkReflexes" }, { "acceleration", "sprintSpeed" }, { "gkPositioning" } },
  [false] = { { "acceleration", "sprintSpeed" }, { "finishing", "shotPower", "longShots" }, { "shortPassing", "longPassing", "vision" },
              { "dribbling", "ballControl", "agility" }, { "standingTackle", "marking", "interceptions" }, { "strength", "stamina", "aggression" } },
}
local FACE_IX
-- Fills row.label1..6 / row.stat1..6 (the card's faces, each the rounded mean of its attributes) from array `a`.
local function faces(row, a, gk)
  if type(a) ~= "table" then return end
  gk = gk and true or false
  if not FACE_IX then
    local PD = PDm()
    local pos = {}
    for i, n in ipairs(PD.ATTRS) do pos[n] = i end
    FACE_IX = {}
    for _, g in ipairs({ true, false }) do
      FACE_IX[g] = {}
      for k, names in ipairs(FACE_SPEC[g]) do local ix = {}; for j, n in ipairs(names) do ix[j] = pos[n] end; FACE_IX[g][k] = ix end
    end
  end
  local labels, spec = FACE_LABELS[gk], FACE_IX[gk]
  for k = 1, 6 do
    local ix = spec[k]
    local s = 0
    for j = 1, #ix do s = s + (a[ix[j]] or 50) end
    row["label" .. k] = row["label" .. k] or labels[k]
    row["stat" .. k] = floor(s / #ix + 0.5)
  end
end
--- A squad row for youth `id` in `club` (what the engine's lineup would hold, with his career values).
function Y.rowFor(id, y, club)
  local row = { CARD_ID = id, playerID = id, rating = Y.ovrOf(id, y) or y.o, position = y.ps or POSNAME[y.p] or "CM",
    playerName = y.nm or ("Youth " .. tostring(id)), teamID = club, jerseyNumber = tonumber(y.js) or 0, isGoalie = y.p == 0,
    isCurrentGK = false, formation = "", nationalityID = tonumber(y.nat) or 0 }
  faces(row, Y.attrsOf(id, y), y.p == 0)
  return row
end
--- Updates a cached squad row of a youth with his current overall and card faces; `ratingOnly` skips the faces (they
--- follow when the club's squad is next cached: Y.inject). Returns false when the row is not a youth's.
function Y.refreshRow(row, ratingOnly)
  local id = type(row) == "table" and tonumber(row.CARD_ID)
  local y = id and Y.get(id)
  if not y then return false end
  row.rating = Y.ovrOf(id, y) or row.rating
  if not ratingOnly then faces(row, Y.attrsOf(id, y), y.p == 0) end
  return true
end

------------------------------------------------------------------------ squads
--- A club's squad was just cached: in with the youths the career has there, out with youths that belong elsewhere (a
--- body still listed by the club the database has him at). Returns how many rows changed.
function Y.inject(teamID)
  local st = Y.state()
  teamID = tonumber(teamID)
  if not st or not teamID then return 0 end
  local cache = cacheOf()
  local e = type(cache) == "table" and cache[teamID] or nil
  if type(e) ~= "table" or type(e.players) ~= "table" then return 0 end
  local SS = SSm()
  local roster = SS and SS.roster and SS.roster() or {}
  local kept, present, changed = {}, {}, 0
  for i = 1, #e.players do
    local row = e.players[i]
    local id = type(row) == "table" and tonumber(row.CARD_ID) or nil
    local y = id and st.reg[id]
    local elsewhere = y ~= nil and not (y.k == "C" and y.club == teamID) and roster[id] ~= teamID
    if elsewhere or (id and present[id]) then changed = changed + 1
    else kept[#kept + 1] = row; if id then present[id] = true end
      if y then Y.refreshRow(row) end
    end
  end
  local mine = index(st)[teamID]
  if mine then
    local ids = {}
    for id in pairs(mine) do if not present[id] then ids[#ids + 1] = id end end
    table.sort(ids)
    for _, id in ipairs(ids) do kept[#kept + 1] = Y.rowFor(id, mine[id], teamID); present[id] = true; changed = changed + 1 end
  end
  if changed > 0 then e.players = kept end
  return changed
end
--- Y.inject for every cached squad (after a load, before the roster is restored); also hands over sessionVars.
function Y.injectAll(sessionVars)
  if type(sessionVars) == "table" then G.sv = sessionVars end
  local cache = cacheOf()
  if type(cache) ~= "table" or not Y.state() then return 0 end
  local n = 0
  for teamID in pairs(cache) do n = n + Y.inject(teamID) end
  if n > 0 then log("load: " .. n .. " youth rows placed in the cached squads") end
  return n
end
-- Removes player `id`'s row from a club's cached squad; true when it was there.
local function removeRow(teamID, id)
  local cache = cacheOf()
  local e = type(cache) == "table" and cache[teamID] or nil
  if type(e) ~= "table" or type(e.players) ~= "table" then return false end
  for i = #e.players, 1, -1 do
    local row = e.players[i]
    if type(row) == "table" and tonumber(row.CARD_ID) == id then table.remove(e.players, i); return true end
  end
  return false
end
-- The database row of player `id` of `club`: from the club's cached squad, else the run's pristine snapshot
-- (sessionVars "fifaSquad"), else by caching the club (getCachedTeamPlayers; counted in G.opened). nil when he is not
-- in that club's lineup.
local function rowOf(id, club)
  local s = sv()
  local function find(e)
    if type(e) ~= "table" or type(e.players) ~= "table" then return nil end
    for i = 1, #e.players do local r = e.players[i]; if type(r) == "table" and tonumber(r.CARD_ID) == id then return r end end
    return nil
  end
  local cache = cacheOf()
  local r = find(type(cache) == "table" and cache[club])
  if r then return r end
  local base = s and s.get and s.get("fifaSquad", true)
  r = find(type(base) == "table" and base[club])
  if r then return r end
  local warm = rawget(_G, "getCachedTeamPlayers")
  if type(warm) == "function" and not (type(cache) == "table" and cache[club]) then
    pcall(warm, club)
    G.opened = (G.opened or 0) + 1
    return find((cacheOf() or {})[club])
  end
  return nil
end
-- Puts a youth into a club's squad now (when the club is cached) or when it next is (Y.inject). Returns whether his row
-- is in the cached squad.
local function place(st, id, y, club)
  y.k = "C"
  setClub(st, id, y, club)
  local cache = cacheOf()
  local e = type(cache) == "table" and cache[club] or nil
  if type(e) == "table" and type(e.players) == "table" and #e.players > 0 then
    for i = 1, #e.players do if tonumber(e.players[i].CARD_ID) == id then return true end end
    e.players[#e.players + 1] = Y.rowFor(id, y, club)
    return true
  end
  return false
end

------------------------------------------------------------------------ new youths
-- Whether body `id` is unused: not a youth, not a retired player, not on a roster.
local function free(st, id, roster)
  return st.reg[id] == nil and st.ret[id] == nil and (roster == nil or roster[id] == nil)
end
-- The host list in this career's order: a seeded shuffle of the clubs, younger players first. Entries are
-- { id, club, pos }, read from PRISM_YOUTH_HOSTS.clubs[club] = a string of "<player id><position letter><birth yy>"
-- (the letter's index in LETTERS - 1 is the position code).
local LETTERS = "abcdefghijklmnopqrstuvwxyzAB"
local function hostList(seed)
  if G.hosts and G.hostsSeed == seed then return G.hosts end
  local T = rawget(_G, "PRISM_YOUTH_HOSTS")
  local clubs = {}
  if type(T) == "table" and type(T.clubs) == "table" then for c in pairs(T.clubs) do clubs[#clubs + 1] = c end end
  table.sort(clubs)
  local r = rng(hash(seed, 7771))
  for i = #clubs, 2, -1 do local j = 1 + floor(r() * i); clubs[i], clubs[j] = clubs[j], clubs[i] end
  local young, rest = {}, {}
  for _, c in ipairs(clubs) do
    for id, pl, yy in tostring(T.clubs[c]):gmatch("(%d+)(%a)(%d%d)") do
      local p = LETTERS:find(pl, 1, true)
      if p then
        yy = tonumber(yy)
        local h = { id = tonumber(id), club = c, pos = p - 1 }
        if yy >= 93 or yy < 40 then young[#young + 1] = h else rest[#rest + 1] = h end
      end
    end
  end
  for _, h in ipairs(rest) do young[#young + 1] = h end
  G.hosts, G.hostsSeed = young, seed
  return young
end
--- How many bodies the host list holds.
Y.hostCount = function(st) return #hostList((st or Y.state() or { seed = 1 }).seed) end
-- `want` = { GK =, DEF =, MID =, ATT =, ANY = } (counts, consumed) -> a list of bodies { id, club, pos }, in the order
-- taken: the spill of earlier batches, the host list from the cursor st.hc, then players retired RECYCLE_AFTER seasons
-- ago. Bodies skipped on the way (wrong line) go to the spill (at most 400) for the next batch.
local function takeHosts(st, want)
  local SS = SSm()
  local roster = SS and SS.roster and SS.roster() or nil
  local out = {}
  local function left() local n = 0 for _, v in pairs(want) do n = n + v end return n end
  local function need(line)
    if (want[line] or 0) > 0 then want[line] = want[line] - 1; return true end
    if (want.ANY or 0) > 0 then want.ANY = want.ANY - 1; return true end
    return false
  end
  local spill = {}
  for _, h in ipairs(st.spill) do
    if left() > 0 and free(st, h.id, roster) and need(lineOf(h.pos)) then out[#out + 1] = h
    elseif free(st, h.id, roster) and #spill < 400 then spill[#spill + 1] = h end
  end
  local list = hostList(st.seed)
  while left() > 0 and st.hc <= #list do
    local h = list[st.hc]
    st.hc = st.hc + 1
    if free(st, h.id, roster) then
      if need(lineOf(h.pos)) then out[#out + 1] = h elseif #spill < 400 then spill[#spill + 1] = h end
    end
  end
  st.spill = spill
  if left() > 0 then
    local cands = {}
    for id, r in pairs(st.ret) do if r.o and r.s >= 0 and st.season - r.s >= CFG.RECYCLE_AFTER then cands[#cands + 1] = id end end
    table.sort(cands)
    for _, id in ipairs(cands) do
      if left() <= 0 then break end
      local r = st.ret[id]
      if need(lineOf(r.p)) then out[#out + 1] = { id = id, club = r.o, pos = r.p, recycled = true } end
    end
  end
  return out
end
-- A club's level now: the average overall of its best 16 cached players (62 when it is not cached).
local function liveTier(teamID)
  local cache = cacheOf()
  local e = type(cache) == "table" and cache[teamID]
  local rs = {}
  if type(e) == "table" and type(e.players) == "table" then
    for i = 1, #e.players do rs[#rs + 1] = tonumber(e.players[i].rating) or 50 end
  end
  table.sort(rs, function(a, b) return a > b end)
  local s, n = 0, 0
  for i = 1, min(16, #rs) do s = s + rs[i]; n = n + 1 end
  return n > 0 and s / n or 62
end
-- The level a club's youths are made for: the club's level the first time the youth system saw it (a new career: the
-- database's squads), kept for the whole career in st.bt. The live level would spiral: a generation a little weaker
-- than the stars it replaces lowers the next generation's potential, and so on (a 49-season run drops the world
-- average from 64.7 to 52.6).
local function baseTier(st, teamID)
  teamID = tonumber(teamID)
  if not teamID then return 62 end
  st.bt = st.bt or {}
  local b = st.bt[teamID]
  if not b then b = floor(liveTier(teamID) + 0.5); st.bt[teamID] = b end
  return b
end
-- Makes a youth of kind `kind` from host body `h`: age in `ages`, potential around `tier`, overall from potential and
-- age; registers him and takes his row out of the club the database lists him at. Returns the youth, or nil when the
-- body's row cannot be read.
local function makeYouth(st, h, kind, ages, tier, r, refYear)
  local row = rowOf(h.id, h.club)
  -- not in that club's lineup (another database): the body is marked unusable for good
  if not row then st.ret[h.id] = { s = -9999 }; return nil end
  local age = ages[1] + floor(r() * (ages[2] - ages[1] + 1))
  local b = dayOf(refYear - age - 1, 7, 2) + floor(r() * 365)
  -- potential around the club's level (its base tier: what its squad was when the career began), so a generation grows
  -- into the players it replaces; one in fifty a wonderkid
  local pot = clamp(floor(tier + 1 + gauss(r) * 6.5 + 0.5), 48, 92)
  if r() < 0.02 then pot = min(94, pot + 8) end
  local ovr = clamp(floor(pot - (23.5 - age) * (2.2 + r() * 1.2) + 0.5), 38, pot)
  local y = { b = b, p = h.pos, t = pot, o = ovr, s = 1 + floor(r() * 999998), c = st.season, k = kind, club = nil,
              org = h.club, nm = row.playerName, nat = tonumber(row.nationalityID), js = tonumber(row.jerseyNumber), ps = row.position }
  if y.ps == nil or POSCODE[tostring(y.ps)] == nil then y.ps = POSNAME[h.pos] end
  st.reg[h.id] = y
  st.ret[h.id] = nil
  removeRow(h.club, h.id)   -- he has left the club the database lists him at
  local SS = SSm()
  if SS and SS.roster then SS.roster()[h.id] = nil end
  return y
end

------------------------------------------------------------------------ retirement
-- Piecewise-linear lookup of x in a list of { x, y } knots; flat outside them.
local function interp(t, x)
  if x <= t[1][1] then return t[1][2] end
  for i = 2, #t do if x <= t[i][1] then local a, b = t[i - 1], t[i]; return a[2] + (b[2] - a[2]) * (x - a[1]) / (b[1] - a[1]) end end
  return t[#t][2]
end
--- The chance (0..1) that a player of `age` years and overall `ovr` retires at a season's end: CFG.RETIRE by age
--- (keepers GK_SHIFT years later, shifted by the career setup's "retire" years), x0.55 from overall 84, x0.75 from
--- 78, x1.3 below 60.
function Y.retireChance(age, ovr, gk)
  local a = gk and (age - CFG.GK_SHIFT) or age
  local PSu = rawget(_G, "PrismSetup")
  if PSu and PSu.get then a = a - (tonumber(PSu.get("retire")) or 0) end   -- the career's retirement age shift
  local p = interp(CFG.RETIRE, a)
  if p <= 0 then return 0 end
  ovr = tonumber(ovr) or 60
  if ovr >= 84 then p = p * 0.55 elseif ovr >= 78 then p = p * 0.75 elseif ovr < 60 then p = min(1, p * 1.3) end
  return p
end
-- A player's birth as a FIFA day number: a youth's own, else CareerDev's database read (nil when unknown).
local function birthOfAny(id)
  local b = Y.birthOf(id)
  if b then return b end
  local CD = rawget(_G, "CareerDev")
  if CD and CD.birthOf then local ok, v = pcall(CD.birthOf, id); if ok and tonumber(v) and v > 0 then return v end end
  return nil
end
-- Removes a retired player from the career's session lists: loans, transfer and loan lists, offers, shortlists,
-- scouting, the current-players list, match sheets, the transferred-players table and the appearance counts.
local function scrub(s, id)
  for _, k in ipairs({ "loanedPlayers", "transferListed", "loanListed", "notListed", "transferOffers", "shortlistedPlayers", "scoutedPlayers" }) do
    local t = s.get(k)
    if type(t) == "table" then t[id] = nil; t[tostring(id)] = nil end
  end
  local cur = s.get("currentPlayersID")
  if type(cur) == "table" then for i = #cur, 1, -1 do if tonumber(cur[i]) == id then table.remove(cur, i) end end end
  local sheets = s.get("sheetData")
  if type(sheets) == "table" then
    for _, sh in pairs(sheets) do
      if type(sh) == "table" and type(sh.players) == "table" then for i = #sh.players, 1, -1 do if tonumber(sh.players[i]) == id then table.remove(sh.players, i) end end end
    end
  end
  local tp = rawget(_G, "transferredPlayers")
  if type(tp) == "table" then tp[id] = nil end
  local apps = s.get("playerAppearances")   -- per league: a retired player's counts are nobody's
  if type(apps) == "table" then for _, lt in pairs(apps) do if type(lt) == "table" then lt[id] = nil; lt[tostring(id)] = nil end end end
end
-- One player retires: out of his squad, out of the career (a youth's body can come back after RECYCLE_AFTER seasons).
local function retireOne(st, id, club, row)
  local s = sv()
  local SS = SSm()
  local y = st.reg[id]
  if y then
    setClub(st, id, y, nil)
    st.reg[id] = nil
    st.ret[id] = { s = st.season, p = y.p, o = y.org }
    if SS and SS.roster then SS.roster()[id] = nil end
  else
    if SS and SS.release then SS.release(id) end
    local org = SS and SS.originIndex and SS.originIndex()[id] or club
    st.ret[id] = { s = st.season, p = rowPos(row), o = org }
  end
  -- his rows leave every cached squad in Y.seasonEnd, one pass for all of the season's retirements
  local PD = PDm()
  if PD and PD.state and PD.state.players then PD.state.players[id] = nil end
  if s then scrub(s, id) end
end

------------------------------------------------------------------------ the clubs
-- The ids of the clubs whose players age and retire, sorted: the career's teams, the leagues simulated without trading,
-- the extra transfer-market leagues, or (League Mode) the user's league, and the user's club.
local function careerClubs()
  local s = sv()
  local out, seen = {}, {}
  local list = s and s.get and s.get("CareerModeTeams")
  local function add(id) id = tonumber(id); if id and id > 0 and not seen[id] then seen[id] = true; out[#out + 1] = id end end
  if type(list) == "table" then for _, t in pairs(list) do add(type(t) == "table" and (t.teamID or t.id) or t) end end
  -- the leagues the career simulates without trading (Processor's SHADOW_SIM_LEAGUES, the Champions League feeders that
  -- SeasonInit schedules): their clubs play every season, so their players age and retire like everyone's
  local lts = s and s.get and s.get("LeagueTeams")
  if #out > 0 and type(lts) == "table" then
    for _, lg in ipairs({ 4, 308 }) do
      if type(lts[lg]) == "table" then for _, t in pairs(lts[lg]) do add(type(t) == "table" and (t.teamID or t.id) or t) end end
    end
  end
  -- and the additional leagues it caches as a transfer market without fixtures (Processor's addExtraLeague: Rest of
  -- World 76, 41, 1): no league table, but players the user can sign - they age, retire and are replaced too
  local cache = #out > 0 and cacheOf() or nil
  if type(cache) == "table" then
    local extra = { [76] = true, [41] = true, [1] = true }
    for id, e in pairs(cache) do if type(e) == "table" and extra[tonumber(e.league) or -1] then add(id) end end
  end
  if #out == 0 then   -- League Mode: the user's league
    local lt = s and s.get and s.get("LeagueTeams")
    local lg = s and s.get and s.get("currentUserLeagueID")
    if type(lt) == "table" and lg and type(lt[lg]) == "table" then for _, t in pairs(lt[lg]) do add(type(t) == "table" and (t.teamID or t.id) or t) end end
  end
  add(rawget(_G, "currentSelectedTeamID"))
  table.sort(out)
  return out
end
-- The cached squad rows of a club, or nil when it is not cached.
local function squadOf(teamID)
  local cache = cacheOf()
  local e = type(cache) == "table" and cache[teamID]
  return type(e) == "table" and type(e.players) == "table" and e.players or nil
end
-- Players per line (GK / DEF / MID / ATT) in a list of squad rows.
local function lineCounts(rows)
  local c = { GK = 0, DEF = 0, MID = 0, ATT = 0 }
  for i = 1, #(rows or {}) do local l = lineOf(rowPos(rows[i])); c[l] = c[l] + 1 end
  return c
end
-- What a club short of `n` players needs, as a list of lines: lines under their minimum first, then the lines it lost
-- (`lost`), then a fixed cycle.
local function needsFor(rows, n, lost)
  local c = lineCounts(rows)
  local out = {}
  for _, l in ipairs(LINES) do
    local short = max(0, CFG.LINE_MIN[l] - c[l])
    for _ = 1, min(short, n - #out) do out[#out + 1] = l end
  end
  for i = 1, #(lost or {}) do if #out < n then out[#out + 1] = lost[i] end end
  local cycle = { "MID", "DEF", "ATT", "MID", "DEF", "GK" }
  local k = 1
  while #out < n do out[#out + 1] = cycle[k]; k = k % #cycle + 1 end
  return out
end
-- The pool's youth ids by line, best potential first (built once per batch; a drawn youth is no longer "P" and is
-- skipped).
local function poolLists(st)
  local by = { GK = {}, DEF = {}, MID = {}, ATT = {} }
  for id, y in pairs(st.reg) do if y.k == "P" then local l = by[lineOf(y.p)]; l[#l + 1] = id end end
  for _, l in pairs(by) do table.sort(l, function(a, b) local ya, yb = st.reg[a], st.reg[b]; if ya.t ~= yb.t then return ya.t > yb.t end return a < b end) end
  return by
end
-- Takes the best pool youth of a line: returns id, y (nil when the pool has none).
local function poolBy(st, line, lists)
  lists = lists or poolLists(st)
  local l = lists[line]
  while l and #l > 0 do
    local id = table.remove(l, 1)
    local y = st.reg[id]
    if y and y.k == "P" then return id, y end
  end
  return nil
end
-- How many youths of a kind ("C" / "P" / "A") exist.
local function count(st, kind)
  local n = 0
  for _, y in pairs(st.reg) do if y.k == kind then n = n + 1 end end
  return n
end

------------------------------------------------------------------------ batches
-- New youths for a list of wants: { { kind=, club=, line= (nil = any), ages=, tier= }, ... }; one host batch for all
-- of them, the clubs they come from opened once each. Kind "C" youths are placed in their club. Returns how many were
-- made.
local function generate(st, wants, refYear, salt)
  if #wants == 0 then return 0 end
  local want = { GK = 0, DEF = 0, MID = 0, ATT = 0, ANY = 0 }
  for _, w in ipairs(wants) do if w.line then want[w.line] = want[w.line] + 1 else want.ANY = want.ANY + 1 end end
  local bodies = takeHosts(st, want)
  local byLine = { GK = {}, DEF = {}, MID = {}, ATT = {} }
  for _, h in ipairs(bodies) do local l = byLine[lineOf(h.pos)]; l[#l + 1] = h end
  local r = rng(hash(st.seed, st.season, salt or 1))
  local made = 0
  local function takeAny()
    for _, l in ipairs({ "MID", "DEF", "ATT", "GK" }) do if #byLine[l] > 0 then return table.remove(byLine[l], 1) end end
    return nil
  end
  for _, w in ipairs(wants) do
    local h = w.line and #byLine[w.line] > 0 and table.remove(byLine[w.line], 1) or (not w.line and takeAny()) or nil
    if h then
      local y = makeYouth(st, h, w.kind, w.ages, w.tier or 62, r, refYear)
      if y then
        made = made + 1
        if w.kind == "C" then place(st, h.id, y, w.club) end
      end
    end
  end
  return made
end

-- Adds wants for the user's academy back up to ACADEMY players, short lines (ACADEMY_MIX) first.
local function topUpAcademy(st, refYear, wants)
  local n = count(st, "A")
  if n >= CFG.ACADEMY then return end
  local have = { GK = 0, DEF = 0, MID = 0, ATT = 0 }
  for _, y in pairs(st.reg) do if y.k == "A" then local l = lineOf(y.p); have[l] = have[l] + 1 end end
  -- an academy's prospects follow the club's level loosely (a big club's academy is better, not a squad of its stars)
  local tier = 60 + (baseTier(st, tonumber(rawget(_G, "currentSelectedTeamID")) or 0) - 60) * 0.6
  local add = CFG.ACADEMY - n
  for _, l in ipairs(LINES) do
    for _ = 1, max(0, CFG.ACADEMY_MIX[l] - have[l]) do
      if add > 0 then wants[#wants + 1] = { kind = "A", line = l, ages = CFG.ACADEMY_AGE, tier = tier }; add = add - 1 end
    end
  end
  for _ = 1, add do wants[#wants + 1] = { kind = "A", ages = CFG.ACADEMY_AGE, tier = tier } end
end
-- Adds wants for the pool back up to POOL players.
local function topUpPool(st, wants)
  local n = count(st, "P")
  for _ = 1, max(0, CFG.POOL - n) do wants[#wants + 1] = { kind = "P", ages = CFG.POOL_AGE, tier = 60 + floor(#wants % 9) * 2 } end
end

--- Creates the youth state of a career that has none (a new career, or a save without youth data): the academy and
--- the pool, plus the base tiers of the cached clubs. Returns the state, or nil outside a career.
function Y.ensure(seed)
  local s = sv()
  if not (s and s.get and s.set) then return nil end
  if not (s.get("InCareerMode") or s.get("InLeagueMode")) then return nil end
  local st = Y.state()
  if st then return st end
  local PD = PDm()
  st = newState(seed or (PD and PD.state and PD.state.seed) or os.time())
  s.set(KEY, st)
  G.index = nil
  local _, year = today()
  year = year or 2025
  for _, club in ipairs(careerClubs()) do if squadOf(club) then baseTier(st, club) end end
  local wants = {}
  topUpAcademy(st, year, wants)
  topUpPool(st, wants)
  local t0 = os.clock()
  local made = generate(st, wants, year, 11)
  log(string.format("new: academy %d, pool %d (%d youths, %d clubs opened, %.0f ms)", count(st, "A"), count(st, "P"), made, G.opened or 0, (os.clock() - t0) * 1000))
  return st
end

-- The youths' year: development for the ones CareerDev does not track (it develops the others month by month). Sets
-- changed[id] for each youth whose overall moved; returns how many did.
local function developYear(st, todayDay, changed)
  local PD = PDm()
  if not (PD and PD.expected) then return 0 end
  local r = rng(hash(st.seed, st.season, 3))
  local n = 0
  for id, y in pairs(st.reg) do
    if not (PD.get and PD.get(id)) then
      local age = years(y.b, todayDay)
      local share = y.k == "C" and 0.45 or 0.25
      local e = PD.expected({ cap = y.t, ovr = y.o, pos = y.p }, age, share, PD.CFG.formBase, 0.5)
      if e > 0 then e = e * (0.85 + r() * 0.3) end
      local o = clamp(floor(y.o + e + 0.5), 1, 99)
      if o > y.t and e > 0 then o = max(y.o, y.t) end
      if o ~= y.o then y.o = o; n = n + 1; if changed then changed[id] = true end end
    end
  end
  return n
end

--- Season end (SeasonInit:initSeason, every club fetched): 1. retirements, 2. a year older (development, academy
--- leavers, the pool's oldest out), 3. each AI club's intake, 4. new ratings onto the cached squad rows. Stores the
--- summary in st.last and returns it (nil when there is no career or date).
function Y.seasonEnd()
  local st = Y.state() or Y.ensure()
  if not st then return nil end
  local s = sv()
  local t0 = os.clock()
  G.opened = 0
  local td, year = today()
  if not td then return nil end
  local user = tonumber(rawget(_G, "currentSelectedTeamID"))
  local clubs = careerClubs()
  -- 1. retirements
  local before, lost, retiring, judged = {}, {}, {}, {}
  local nJudged, nNoBirth, nClubs = 0, 0, 0
  -- Player Career: the user's own player retires when the user says so, never by the roll below
  do local PRO = rawget(_G, "PrismPro"); local pid = PRO and PRO.id and PRO.id(); if pid then judged[pid] = true end end
  for _, club in ipairs(clubs) do
    local rows = squadOf(club)
    if rows then
      before[club] = #rows
      nClubs = nClubs + 1
      for i = 1, #rows do
        local row = rows[i]
        local id = tonumber(row.CARD_ID)
        if id and judged[id] then id = nil end   -- listed by two clubs: judged once
        if id then judged[id] = true end
        local b = id and birthOfAny(id)
        if id then nJudged = nJudged + 1; if not b then nNoBirth = nNoBirth + 1 end end
        if b then
          local p = Y.retireChance(years(b, td), Y.ovrOf(id) or tonumber(row.rating), rowPos(row) == 0)
          if p > 0 and rng(hash(id, st.season, st.seed))() < p then retiring[#retiring + 1] = { id = id, club = club, row = row } end
        end
      end
    end
  end
  local tRetireJudge = os.clock()
  local mine, notable, gone = {}, {}, {}
  for _, it in ipairs(retiring) do
    lost[it.club] = lost[it.club] or {}
    table.insert(lost[it.club], lineOf(rowPos(it.row)))
    if it.club == user then mine[#mine + 1] = tostring(it.row.playerName or it.id) end
    if (tonumber(it.row.rating) or 0) >= 82 then notable[#notable + 1] = tostring(it.row.playerName or it.id) end
    retireOne(st, it.id, it.club, it.row)
    gone[it.id] = true
  end
  -- every cached squad without them, in one pass (a player the database lists twice - a Rest of World or national side
  -- as well as his club - leaves both)
  if next(gone) then
    for _, e in pairs(cacheOf() or {}) do
      local ps = type(e) == "table" and e.players
      if type(ps) == "table" then
        local keep, any = {}, false
        for i = 1, #ps do local id = tonumber(ps[i].CARD_ID); if id and gone[id] then any = true else keep[#keep + 1] = ps[i] end end
        if any then e.players = keep end
      end
    end
  end
  local tRetired = os.clock()
  st.season = st.season + 1
  -- 2. a year older: development, academy leavers, the pool's oldest out
  local moved = {}
  local developed = developYear(st, td, moved)
  local tDeveloped = os.clock()
  local promoted, released, agedOut = {}, 0, 0
  local userRows = user and squadOf(user) or {}
  for id, y in pairs(st.reg) do
    local age = years(y.b, dayOf(year, 7, 1))
    if y.k == "A" and age >= CFG.ACADEMY_LEAVE then
      if #userRows + #promoted < CFG.USER_SQUAD_MAX and (y.o >= 58 or y.t >= 72) then promoted[#promoted + 1] = id
      else y.k = "P"; setClub(st, id, y, nil); released = released + 1 end
    elseif y.k == "P" and age >= CFG.POOL_AGE_OUT then
      st.reg[id] = nil
      st.ret[id] = { s = st.season - CFG.RECYCLE_AFTER + 2, p = y.p, o = y.org }
      agedOut = agedOut + 1
    end
  end
  table.sort(promoted)
  for _, id in ipairs(promoted) do place(st, id, st.reg[id], user) end
  -- 3. intake: each AI club replaces its retired players (up to MAX_SQUAD) and comes back to MIN_SQUAD
  local wants, fromPool = {}, 0
  local lists = poolLists(st)
  for _, club in ipairs(clubs) do
    if club ~= user then
      local rows = squadOf(club)
      if rows then
        local target = max(CFG.MIN_SQUAD, min(before[club] or #rows, CFG.MAX_SQUAD))
        local n = target - #rows
        -- a club with fewer than two keepers gets one even at full strength (up to MAX_SQUAD)
        local keepers = lineCounts(rows).GK
        if keepers < 2 then n = max(n, min(2 - keepers, CFG.MAX_SQUAD - #rows)) end
        if n > 0 then
          local tier = baseTier(st, club)
          for _, line in ipairs(needsFor(rows, n, lost[club])) do
            local id, y = poolBy(st, line, lists)
            if id then place(st, id, y, club); fromPool = fromPool + 1
            else wants[#wants + 1] = { kind = "C", club = club, line = line, ages = CFG.CLUB_AGE, tier = tier } end
          end
        end
      end
    end
  end
  topUpAcademy(st, year, wants)
  topUpPool(st, wants)
  local tIntake = os.clock()
  local made = generate(st, wants, year, 29)
  local tMade = os.clock()
  -- 4. squads: the new ratings on the rows of the youths whose overall moved (new rows were built with theirs); the
  -- card faces too in the user's league, the squads he looks at (elsewhere they follow at the club's next caching)
  local cache = cacheOf() or {}
  if next(moved) then
    local near = {}
    if user then near[user] = true end
    local lt = s and s.get and s.get("LeagueTeams")
    local lg = s and s.get and s.get("currentUserLeagueID")
    if type(lt) == "table" and lg and type(lt[lg]) == "table" then
      for _, x in pairs(lt[lg]) do local cid = tonumber(type(x) == "table" and (x.teamID or x.id) or x); if cid then near[cid] = true end end
    end
    for _, club in ipairs(clubs) do
      local rows = cache[club] and cache[club].players
      if type(rows) == "table" then
        local only = not near[club]
        for i = 1, #rows do local id = tonumber(rows[i].CARD_ID); if id and moved[id] then Y.refreshRow(rows[i], only) end end
      end
    end
  end
  local tEnd = os.clock()
  local pre = G.prefetched; G.prefetched = 0
  st.last = { season = st.season, retired = #retiring, mine = mine, notable = notable, promoted = #promoted, released = released,
              intake = made + fromPool, fromPool = fromPool, academy = count(st, "A"), pool = count(st, "P") }
  if s and s.set then s.set(KEY, st) end
  log(string.format("season %d: %d clubs, %d players judged (%d without a birthdate); %d retired (yours: %s), %d youths developed, academy: %d promoted, %d to the pool; intake %d (%d from the pool); pool %d, academy %d, registry %d; %d clubs opened (%d opened ahead in the hub); %.0f ms (retire %.0f + %.0f, develop %.0f, intake %.0f, new youths %.0f, rows %.0f)",
    st.season, nClubs, nJudged, nNoBirth, #retiring, #mine > 0 and table.concat(mine, ", ") or "none", developed, #promoted, released, made + fromPool, fromPool,
    st.last.pool, st.last.academy, Y.count(), G.opened or 0, pre or 0, (tEnd - t0) * 1000, (tRetireJudge - t0) * 1000, (tRetired - tRetireJudge) * 1000,
    (tDeveloped - tRetired) * 1000, (tIntake - tDeveloped) * 1000, (tMade - tIntake) * 1000, (tEnd - tMade) * 1000))
  return st.last
end
--- How many youths exist.
function Y.count() local st = Y.state(); local n = 0; if st then for _ in pairs(st.reg) do n = n + 1 end end return n end

------------------------------------------------------------------------ during the season
-- Whether a player is injured or suspended in league `lg` (PRISM_SUSP).
local function unavailable(id, lg)
  local S = rawget(_G, "PRISM_SUSP")
  if not (S and S.unavailable) then return false end
  local ok, v = pcall(S.unavailable, id, lg)
  return ok and v and true or false
end
--- A club about to play needs FIT_MIN fit players and a fit keeper, or it gets youths (a keeper first when it has
--- none; at most 4 in all) from the pool (the user: the best academy players). Returns how many were added.
function Y.checkClub(teamID, lg)
  local st = Y.state()
  local rows = squadOf(teamID)
  if not st or not rows then return 0 end
  local fit, keeper = 0, false
  for i = 1, #rows do
    local id = tonumber(rows[i].CARD_ID)
    if id and not unavailable(id, lg) then fit = fit + 1; if rowPos(rows[i]) == 0 then keeper = true end end
  end
  if fit >= CFG.FIT_MIN and keeper then return 0 end
  local user = tonumber(rawget(_G, "currentSelectedTeamID"))
  local added = 0
  local function bring(line)
    local id, y
    if teamID == user then
      for i2, y2 in pairs(st.reg) do if y2.k == "A" and lineOf(y2.p) == line and (not y or y2.o > y.o or (y2.o == y.o and i2 < id)) then id, y = i2, y2 end end
    else id, y = poolBy(st, line) end
    if not id then return false end
    place(st, id, y, teamID)
    added = added + 1
    return true
  end
  if not keeper then bring("GK") end
  local guard = 0
  while fit + added < CFG.FIT_MIN and added < 4 and guard < 8 do
    guard = guard + 1
    local c = lineCounts(rows)
    local line = (c.DEF <= c.MID and c.DEF <= c.ATT * 2) and "DEF" or (c.MID <= c.ATT * 2 and "MID" or "ATT")
    if not bring(line) and not bring("MID") then break end
  end
  if added > 0 then log(string.format("club %d short (%d fit%s): %d youth%s called up", teamID, fit, keeper and "" or ", no keeper", added, added == 1 and "" or "s")) end
  return added
end
--- Date:advanceDate: runs Y.checkClub for both clubs of every unplayed fixture today. Returns the youths added.
function Y.onDay()
  local st = Y.state()
  local s = sv()
  if not st or not (s and s.get) then return 0 end
  local _, y, m, d = today()
  if not y then return 0 end
  local key = string.format("%02d%02d%02d", m, d, y % 100)
  local md = s.get("MatchData")
  if type(md) ~= "table" then return 0 end
  if G.mdRef ~= md or G.mdN ~= #md then   -- by date, rebuilt when the fixtures change
    local by = {}
    for i = 1, #md do local e = md[i]; if type(e) == "table" and e.date then local t = by[e.date]; if not t then t = {}; by[e.date] = t end; t[#t + 1] = e end end
    G.mdBy, G.mdRef, G.mdN = by, md, #md
  end
  local n = 0
  for _, e in ipairs(G.mdBy[key] or {}) do
    if not e.played then
      n = n + Y.checkClub(tonumber(e.homeID), e.leagueID) + Y.checkClub(tonumber(e.awayID), e.leagueID)
    end
  end
  return n
end

------------------------------------------------------------------------ the academy (UI)
--- The user's academy players, best potential first: { id, name, pos, line, age, ovr, pot, nat }.
function Y.academy()
  local st = Y.state()
  local out = {}
  if not st then return out end
  local td = today() or dayOf(2025, 7, 1)
  for id, y in pairs(st.reg) do
    if y.k == "A" then out[#out + 1] = { id = id, name = y.nm or ("#" .. id), pos = y.ps or POSNAME[y.p], line = lineOf(y.p), age = floor(years(y.b, td)), ovr = y.o, pot = y.t, nat = y.nat } end
  end
  table.sort(out, function(a, b) if a.pot ~= b.pot then return a.pot > b.pot end return a.id < b.id end)
  return out
end
--- Promotes an academy player into the user's first-team squad. Returns whether he was promoted.
function Y.promote(id)
  local st = Y.state()
  id = tonumber(id)
  local y = st and id and st.reg[id]
  local user = tonumber(rawget(_G, "currentSelectedTeamID"))
  if not (y and y.k == "A" and user) then return false end
  place(st, id, y, user)
  log("academy: " .. tostring(y.nm or id) .. " promoted to the first team")
  return true
end
--- Releases an academy player into the pool (the other clubs draw from it). Returns whether he was released.
function Y.release(id)
  local st = Y.state()
  id = tonumber(id)
  local y = st and id and st.reg[id]
  if not (y and y.k == "A") then return false end
  y.k = "P"
  setClub(st, id, y, nil)
  log("academy: " .. tostring(y.nm or id) .. " released (into the pool)")
  return true
end
--- Player Career (PrismPro): host body `id` (listed by the database at club `org`) becomes the user's created player at
--- `club`, a youth of kind "C" with birth day `b`, position code `pos`, potential `pot`, overall `ovr`, attribute seed
--- `seed` and jersey number `js`. He leaves his database club and is placed like a promoted academy player; from then on
--- he is saved, restored and developed like any youth (PrismPro keeps him out of the retirements). A body that is
--- already a youth is taken as he is. Returns the youth, or nil and the reason.
function Y.adoptPro(id, org, club, b, pos, pot, ovr, seed, js)
  local st = Y.state() or Y.ensure()
  id, org, club = tonumber(id), tonumber(org), tonumber(club)
  if not (st and id and club) then return nil, "no youth state" end
  local y = st.reg[id]
  if not y then
    local row = org and rowOf(id, org)
    if not row then return nil, "player " .. id .. " is not in the lineup of club " .. tostring(org) end
    y = { b = floor(tonumber(b) or 0), p = tonumber(pos) or 25, t = tonumber(pot) or 80, o = tonumber(ovr) or 60,
          s = floor(tonumber(seed) or 1), c = st.season, k = "C", club = nil, org = org, nm = row.playerName,
          nat = tonumber(row.nationalityID), js = tonumber(js) or tonumber(row.jerseyNumber), ps = POSNAME[tonumber(pos) or 25] }
    st.reg[id] = y
    st.ret[id] = nil
    removeRow(org, id)
    local SS = SSm()
    if SS and SS.roster then SS.roster()[id] = nil end
    log("player career: " .. tostring(y.nm or id) .. " (" .. y.ps .. ") created at club " .. club)
  end
  place(st, id, y, club)
  return y
end
--- Player Career: the created player moved to `club` (an accepted offer). Only a created player (a youth) has a club of
--- his own here; for a squad player the roster move is all there is. Returns whether he is a youth.
function Y.setProClub(id, club)
  local st = Y.state()
  id, club = tonumber(id), tonumber(club)
  local y = st and id and st.reg[id]
  if not (y and club) then return false end
  y.k = "C"
  setClub(st, id, y, club)
  return true
end

--- The hub's Youth Academy card: the academy screen on the shared Popup overlay (src/models/popup/academy.lua reads
--- the academy live and promotes / releases in place; Back closes it). `owner` is the hub screen (its FCPopup is used).
function Y.openAcademy(owner)
  if not Y.state() then Y.ensure() end
  local PS = rawget(_G, "PrismSlots")
  local popup = (type(owner) == "table" and owner.FCPopup) or (PS and PS.hubPopup)
  if not (type(popup) == "table" and type(popup.showAcademy) == "function") then log("academy: no popup to show it on"); return false end
  local list = Y.academy()
  local names = {}
  for i = 1, min(3, #list) do names[#names + 1] = list[i].name .. " (" .. list[i].pos .. ", " .. list[i].ovr .. "/" .. list[i].pot .. ")" end
  popup:showAcademy({
    title = "Youth Academy",
    hint = "Your best prospects. Promote one to the first team, or release him to the other clubs.",
    -- the stock layout (native screens off) can only say what is there
    text = #list > 0 and ("Academy: " .. #list .. " players. Best: " .. table.concat(names, "; ") .. ". The academy screen needs the native screens.")
      or "Your academy is empty until the season starts.",
  }, function() local cd = rawget(_G, "CareerDev"); if cd and cd.overridesStale then pcall(cd.overridesStale) end end)
  return true
end

------------------------------------------------------------------------ CareerDev
--- CareerDev starts tracking a youth in PlayerDev: his career values, with the database row's (his host's `hostAttrs`
--- by attribute name, `hostOvr`) as the base, so the match override table carries every attribute that differs from
--- what the engine reads. Returns false for a non-youth.
function Y.track(id, team, rank, hostAttrs, hostOvr)
  local PD = PDm()
  local y = Y.get(id)
  if not (PD and PD.track and y) then return false end
  local a = Y.attrsAt(y) or {}
  local named = {}
  for i, n in ipairs(PD.ATTRS) do named[n] = a[i] end
  local p = PD.track(id, { pos = y.p, ir = 1, birth = y.b, pot = y.t, ovr = y.o, attrs = named, team = team, rank = rank })
  if p then
    local b = {}
    for i, n in ipairs(PD.ATTRS) do b[i] = clamp(floor(tonumber(type(hostAttrs) == "table" and hostAttrs[n]) or 0), 0, 99) end
    p.b = b
    p.ovr0 = tonumber(hostOvr) or 0
  end
  return true
end
--- A PlayerDev-shaped record { ovr, ovr0 = 0, a, b = zeros } for a youth CareerDev does not track, for the match
--- override table (all his attributes and his overall differ from the host row). nil for a non-youth.
function Y.pdLike(id)
  local y = Y.get(id)
  if not y then return nil end
  local a = Y.attrsOf(id, y)
  if not a then return nil end
  local zero = {}
  for i = 1, #a do zero[i] = 0 end
  return { ovr = y.o, ovr0 = 0, a = a, b = zero }
end

------------------------------------------------------------------------ save
-- Empty string for nil, else tostring.
local function enc(v) if v == nil then return "" end return tostring(v) end
--- The saved form of the state: { v, seed, season, hc, last, r, x, sp, bt }. `r` is one line per youth,
--- "id,birth,pos,pot,ovr,seed,created,kind,club,origin,nationality,jersey,position name,name"; `x` the retired
--- bodies "id:season:pos:origin" joined by commas; `sp` the spill "id:club:pos"; `bt` the base tiers "club:tier".
--- nil when there is no state.
function Y.serialize()
  local st = Y.state()
  if not st then return nil end
  local ids = {}
  for id in pairs(st.reg) do ids[#ids + 1] = id end
  table.sort(ids)
  local lines = {}
  for _, id in ipairs(ids) do
    local y = st.reg[id]
    local nm = tostring(y.nm or ""):gsub("[\r\n]", " ")
    local ps = (y.ps ~= nil and y.ps ~= POSNAME[y.p]) and y.ps or nil   -- the position's own name is implied
    lines[#lines + 1] = table.concat({ id, y.b, y.p, y.t, y.o, y.s, y.c, y.k, enc(y.club), enc(y.org), enc(y.nat), enc(y.js), enc(ps), nm }, ",")
  end
  local rids = {}
  for id in pairs(st.ret) do rids[#rids + 1] = id end
  table.sort(rids)
  local ret = {}
  for _, id in ipairs(rids) do local r = st.ret[id]; ret[#ret + 1] = id .. ":" .. r.s .. ":" .. enc(r.p) .. ":" .. enc(r.o) end
  local sp = {}
  for _, h in ipairs(st.spill) do sp[#sp + 1] = h.id .. ":" .. h.club .. ":" .. h.pos end
  local bts = {}
  local clubs = {}
  for c in pairs(st.bt or {}) do clubs[#clubs + 1] = c end
  table.sort(clubs)
  for _, c in ipairs(clubs) do bts[#bts + 1] = c .. ":" .. st.bt[c] end
  return { v = 1, seed = st.seed, season = st.season, hc = st.hc, r = table.concat(lines, "\n"), x = table.concat(ret, ","),
           sp = table.concat(sp, ","), bt = table.concat(bts, ","), last = st.last }
end
--- Rebuilds the state from Y.serialize output (nil for anything else).
function Y.decode(t)
  if type(t) ~= "table" then return nil end
  local st = newState(t.seed)
  st.season, st.hc, st.last = tonumber(t.season) or 0, tonumber(t.hc) or 1, t.last
  for line in tostring(t.r or ""):gmatch("[^\n]+") do
    local f = {}
    local pos = 1
    for i = 1, 13 do
      local c = line:find(",", pos, true)
      if not c then break end
      f[i] = line:sub(pos, c - 1)
      pos = c + 1
    end
    if #f == 13 then
      local id = tonumber(f[1])
      if id then
        st.reg[id] = { b = tonumber(f[2]) or 0, p = tonumber(f[3]) or 14, t = tonumber(f[4]) or 60, o = tonumber(f[5]) or 50,
          s = tonumber(f[6]) or 1, c = tonumber(f[7]) or 0, k = f[8], club = tonumber(f[9]), org = tonumber(f[10]),
          nat = tonumber(f[11]), js = tonumber(f[12]), ps = f[13] ~= "" and f[13] or nil, nm = line:sub(pos) }
        if not st.reg[id].ps then st.reg[id].ps = POSNAME[st.reg[id].p] end
      end
    end
  end
  for id, s, p, o in tostring(t.x or ""):gmatch("(%d+):(%-?%d+):(%d*):(%d*)") do
    st.ret[tonumber(id)] = { s = tonumber(s), p = tonumber(p), o = tonumber(o) }
  end
  for id, c, p in tostring(t.sp or ""):gmatch("(%d+):(%d+):(%d+)") do st.spill[#st.spill + 1] = { id = tonumber(id), club = tonumber(c), pos = tonumber(p) } end
  for c, b in tostring(t.bt or ""):gmatch("(%d+):(%d+)") do st.bt[tonumber(c)] = tonumber(b) end
  return st
end

------------------------------------------------------------------------ binding
--- The hub binds: hands over sessionVars, resets the birthdate warm-up and makes sure the career has youth data.
function Y.bind(sessionVars)
  if type(sessionVars) == "table" then G.sv = sessionVars end
  G.warmQ = nil
  return Y.ensure()
end
--- The hub's update, once per frame: reads the database birthdates the season end's retirements need, `budget` (default
--- 8) per frame. The first read of a player's birthdate is a native call (CareerDev keeps it for the session); spread
--- over the hub's frames, the season end finds them read instead of making them all at once. Returns how many it read.
function Y.step(budget)
  local st = Y.state()
  local CD = rawget(_G, "CareerDev")
  if not (st and CD and CD.birthOf and type(CD.G) == "table" and type(CD.G.births) == "table") then return 0 end
  local cache = cacheOf()
  if type(cache) ~= "table" then return 0 end
  local q = G.warmQ
  if not q or (G.warmQi > #q and (G.warmAt or 0) + 600 < (G.frames or 0)) then
    local ncl = 0
    q = {}
    for _, club in ipairs(careerClubs()) do
      local rows = cache[club] and cache[club].players
      if type(rows) == "table" then
        ncl = ncl + 1
        for i = 1, #rows do local id = tonumber(rows[i].CARD_ID); if id and not st.reg[id] then q[#q + 1] = id end end
      end
    end
    if G.warmQ and ncl == G.warmClubs then G.warmQi = #q + 1 else G.warmQi = 1 end
    G.warmQ, G.warmClubs, G.warmAt = q, ncl, G.frames or 0
  end
  G.frames = (G.frames or 0) + 1
  local births, PD = CD.G.births, PDm()
  local n = 0
  while G.warmQi <= #q and n < (budget or 8) do
    local id = q[G.warmQi]
    G.warmQi = G.warmQi + 1
    if births[id] == nil and not (PD and PD.get and PD.get(id)) then pcall(CD.birthOf, id); n = n + 1 end
  end
  -- March to May: the clubs the season end's new youths will come from (the host order is fixed per career), opened
  -- ahead, one every PREFETCH_EVERY frames (one engine lineup call each), so the season end finds their names cached
  if G.frames % Y.PREFETCH_EVERY == 0 then
    local _, _, m = today()
    if m and m >= 3 and m <= 5 then
      local key = st.season .. ":" .. st.hc
      if G.pfKey ~= key then G.pfKey, G.pfList, G.pfI = key, Y.upcomingClubs(st, 2600), 1 end
      local warm = rawget(_G, "getCachedTeamPlayers")
      while G.pfI <= #G.pfList and type(warm) == "function" do
        local club = G.pfList[G.pfI]
        G.pfI = G.pfI + 1
        if not cache[club] then pcall(warm, club); G.prefetched = (G.prefetched or 0) + 1; break end
      end
    end
  end
  return n
end
Y.PREFETCH_EVERY = 20   -- frames between two prefetched clubs
--- The clubs of the next `n` bodies the host list would give (the spill first), each once.
function Y.upcomingClubs(st, n)
  local list = hostList(st.seed)
  local out, seen = {}, {}
  for _, h in ipairs(st.spill) do if not seen[h.club] then seen[h.club] = true; out[#out + 1] = h.club end end
  local i, k = st.hc, 0
  while i <= #list and k < n do
    local h = list[i]
    i, k = i + 1, k + 1
    if not seen[h.club] then seen[h.club] = true; out[#out + 1] = h.club end
  end
  return out
end

rawset(_G, "PrismYouth", Y)
return Y
