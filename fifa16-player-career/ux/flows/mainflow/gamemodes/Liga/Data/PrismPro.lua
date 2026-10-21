--[[ PrismPro.lua - Player Career: the user's own player ("the pro").

The game cannot add a player to its database, and every player has his own head, face and hair models (the database's
"has high quality head" flag is set for all but a handful of its 57,916 players). A created player is therefore a real
database row: one of PrismYouth's host bodies (players of clubs in leagues outside the career, PrismProFaces.lua),
whose face, hair and body are what the user picks. Everything else is the user's build: position, age, potential,
starting level and where the attribute points go. The body becomes a PrismYouth youth of kind "C" at the user's club
(PrismYouth.adoptPro), so the squad rows, the saves and the matches treat him like every other youth; PlayerDev tracks
him from day one with the build's attributes (real matches get them through the engine's match override table, the
same as all development), and he grows, peaks and declines like everyone else.

The other way into a player career is the stock one: play as a player already in the chosen club's squad
(PlayerSelector). Both end with sessionVars "PlayerCareerPlayerID" set; PlayerCareer.lua then runs the matchday (the AI
manager's team sheet, simulating the matches the user's player does not start).

What PrismPro owns
  * Create Your Player (PRO.open): the Career Setup screen (Popup mode "setup") with its own rows and a 3D model in
    slot 4, opened from TeamSelect's last boot step for a new player career (PRO.start asks which way first).
  * The pro's career: appearances, starts, minutes, goals, assists, man-of-the-match awards, clean sheets and the
    average rating (career, season, the last 10 matches, one line per finished season) from CareerDev.recordMatch.
  * Manager trust (0..100): every match he plays moves it by his rating; each month it drifts towards what his overall
    is worth in the squad. It decides how often the AI manager starts him (PRO.adjustXI, called by PlayerCareer's
    pickAISquad) and his squad role.
  * Offers for the pro: asked on the hub when it is idle (PRO.step) and from the hub's My Offers card (PRO.offers).
  * My Player (PRO.openProfile): the Player Profile screen (PrismProfile) on the pro.

State: sessionVars "_prismPro" (saved with the career as `pro`, PRO.serialize / PRO.restore):
  { v, id, kind ("new" created / "squad" an existing player), club (the club he started at), org (the body's database
    club, "new" only), pos (position code 0..27), age (at creation), ovr, pot, b (birth, FIFA day), seed, js (jersey),
    focus = { pac, sho, pas, dri, def, phy } (-2..2), a0 (the build's attributes as a 66-digit string), pending (the
    build is waiting for the hub to apply it), trust, car / sea = { apps, starts, mins, goals, assists, motm, cs, rs, rn }
    (career / this season; rs / rn the rating sum and count), season (the season `sea` belongs to), hist = { { y, club,
    apps, goals, assists, avg, ovr } } per finished season, last = { { d, opp, r, g, a, m, s, res } } (newest first) }

Hooks (every one guarded; the stock code runs when this module is missing):
  TeamSelect step 5     PRO.start            a new player career: Create Your Player or a squad player
  MatchSelect (hub)     PRO.bind / PRO.step  applies a pending build, keeps the pro's row and id; asks about offers
  CareerDev.recordMatch PRO.onMatch          CareerDev.onSeasonEnd   PRO.onSeasonEnd
  PlayerCareer          PRO.adjustXI         PrismYouth.seasonEnd    PRO.id (the pro never retires by the roll)
  Serializer / LoadSave PRO.serialize / PRO.restore
  Liga/Cores/tabsData   My Player (PRO.openProfile), My Offers (PRO.offers)
]]
local PRO = rawget(_G, "PrismPro") or {}
rawset(_G, "PrismPro", PRO)
PRO.VERSION = 1
PRO.KEY = "_prismPro"
PRO.SLOT = 4   -- the 3D model's slot on Create Your Player (the hub owns 0-1, the editor 2, the profile 3)

local floor, max, min = math.floor, math.max, math.min
local function clamp(v, a, b) if v < a then return a elseif v > b then return b end return v end

-- Shared module state in the global PRISM_PRO (every screen has its own copy of this file): the sessionVars handed
-- over by PRO.bind, the squad service, the session's offer answers and the idle counter of the hub.
local G = rawget(_G, "PRISM_PRO")
if type(G) ~= "table" then G = { asked = {} }; rawset(_G, "PRISM_PRO", G) end
PRO.G = G

local function sv() return G.sv or rawget(_G, "CAREER_SESSION_VARS") end
local function log(msg)
  local f = rawget(_G, "F16_SVC")
  if f and f.Cmd then pcall(f.Cmd, "log:pro: " .. tostring(msg)) end
end
PRO.log = log
local function PDm() return rawget(_G, "PlayerDev") end
local function Ym() return rawget(_G, "PrismYouth") end
-- The variant's translation of one English string (PRISM_I18N; the string itself without it). Texts the native screens
-- show whole are translated there; a text put together here from pieces translates its pieces first.
local function tr(s)
  local I = rawget(_G, "PRISM_I18N")
  if I and I.tr then local ok, r = pcall(I.tr, s); if ok and type(r) == "string" then return r end end
  return s
end

-- Seeded Park-Miller generator (as in PlayerDev and PrismYouth): returns a function giving floats in (0, 1).
local function rng(seed)
  local s = floor(seed) % 2147483646 + 1
  for _ = 1, 4 do s = (s * 16807) % 2147483647 end
  return function() s = (s * 16807) % 2147483647; return s / 2147483647 end
end

------------------------------------------------------------------------ state
local function state()
  local s = sv()
  local ok, st = pcall(function() return s and s.get(PRO.KEY) end)
  return ok and type(st) == "table" and st or nil
end
PRO.state = state
local function save(st) local s = sv(); if s and s.set then s.set(PRO.KEY, st) end end
--- Whether a player career is being played.
function PRO.active()
  local s = sv()
  local ok, on = pcall(function() return s and s.get("InPlayerCareerMode") end)
  return ok and on == true
end
--- The pro's player id, or nil outside a player career.
function PRO.id()
  if not PRO.active() then return nil end
  local st = state()
  local id = st and tonumber(st.id)
  if id then return id end
  local s = sv()
  return s and tonumber(s.get("PlayerCareerPlayerID")) or nil
end
function PRO.isPro(id) local p = PRO.id(); return p ~= nil and tonumber(id) == p end

local function emptyStats() return { apps = 0, starts = 0, mins = 0, goals = 0, assists = 0, motm = 0, cs = 0, rs = 0, rn = 0 } end
local function today()
  local PD = PDm()
  local s = tostring(rawget(_G, "GLOBAL_DATE_PLACEHOLDER") or "")
  return PD and PD.dayOfCareer and PD.dayOfCareer(s) or nil
end
-- The year the current season started in (a season runs July to June), from the career date "DD/MM/YY".
local function seasonYear()
  local _, m, yy = tostring(rawget(_G, "GLOBAL_DATE_PLACEHOLDER") or ""):match("^(%d+)/(%d+)/(%d+)$")
  if not m then return tonumber(rawget(_G, "CAREER_FULL_YEAR")) or 2025 end
  local y = 2000 + tonumber(yy)
  if tonumber(m) < 7 then y = y - 1 end
  return y
end

------------------------------------------------------------------------ positions and the build
-- The positions Create Your Player offers: { label, position code (PlayerDev.GROUP's 0..27) }.
PRO.POSITIONS = { { "Striker (ST)", 25 }, { "Centre Forward (CF)", 21 }, { "Left Winger (LW)", 27 }, { "Right Winger (RW)", 23 },
  { "Attacking Mid (CAM)", 18 }, { "Left Mid (LM)", 16 }, { "Right Mid (RM)", 12 }, { "Central Mid (CM)", 14 },
  { "Defensive Mid (CDM)", 10 }, { "Left Back (LB)", 7 }, { "Right Back (RB)", 3 }, { "Centre Back (CB)", 5 },
  { "Goalkeeper (GK)", 0 } }
local POSNAME = { [0] = "GK", "SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB", "RDM", "CDM", "LDM", "RM", "RCM", "CM",
  "LCM", "LM", "RAM", "CAM", "LAM", "RF", "CF", "LF", "RW", "RS", "ST", "LS", "LW" }
PRO.POSNAME = POSNAME
-- The six focus areas (the card's faces) and the attributes each one moves; the keeper skills follow none of them.
PRO.FOCUS = { "pac", "sho", "pas", "dri", "def", "phy" }
PRO.FOCUS_LABEL = { pac = "PAC", sho = "SHO", pas = "PAS", dri = "DRI", def = "DEF", phy = "PHY" }
local FOCUS_OF = { acceleration = "pac", sprintSpeed = "pac",
  finishing = "sho", shotPower = "sho", longShots = "sho", volleys = "sho", penalties = "sho", positioning = "sho",
  shortPassing = "pas", longPassing = "pas", vision = "pas", crossing = "pas", curve = "pas", freeKickAccuracy = "pas",
  dribbling = "dri", ballControl = "dri", agility = "dri", balance = "dri", reactions = "dri",
  standingTackle = "def", slidingTackle = "def", marking = "def", interceptions = "def", headingAccuracy = "def",
  strength = "phy", stamina = "phy", aggression = "phy", jumping = "phy" }
-- The card's six faces, each the rounded mean of its attributes (the same as PrismYouth's squad rows).
local FACE = { pac = { "acceleration", "sprintSpeed" }, sho = { "finishing", "shotPower", "longShots" },
  pas = { "shortPassing", "longPassing", "vision" }, dri = { "dribbling", "ballControl", "agility" },
  def = { "standingTackle", "marking", "interceptions" }, phy = { "strength", "stamina", "aggression" } }
local GKFACE = { { "DIV", { "gkDiving" } }, { "HAN", { "gkHandling" } }, { "KIC", { "gkKicking" } },
  { "REF", { "gkReflexes" } }, { "SPD", { "acceleration", "sprintSpeed" } }, { "POS", { "gkPositioning" } } }
local FOCUS_STEP = 7   -- attribute points per focus step

--- The build's 33 attributes (PlayerDev.ATTRS order, 5..99) for position code `pos` at overall `ovr`: the position's
--- profile (PlayerDev's formula weights, as PrismYouth makes its youths) with the player's own noise (`seed`), moved
--- by the focus (each step FOCUS_STEP points; the six steps are centred, so a strength is paid for elsewhere), then
--- shifted by one common amount until the game's overall formula gives exactly `ovr`. nil without PlayerDev.
function PRO.attrs(pos, ovr, focus, seed)
  local PD = PDm()
  if not (PD and PD.ATTRS and PD.W and PD.formulaArr) then return nil end
  pos = tonumber(pos) or 25
  local grp = PD.GROUP[pos] or "ST"
  local w = PD.W[grp] or {}
  local gk = grp == "GK"
  focus = type(focus) == "table" and focus or {}
  local mean = 0
  for _, k in ipairs(PRO.FOCUS) do mean = mean + (tonumber(focus[k]) or 0) end
  mean = mean / #PRO.FOCUS
  local r = rng(tonumber(seed) or 1)
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
    local f = FOCUS_OF[n]
    local lift = f and ((tonumber(focus[f]) or 0) - mean) * FOCUS_STEP or 0
    raw[i] = base + floor((r() * 2 - 1) * 6 + 0.5) + floor(lift + 0.5)
  end
  local function ovrAt(k)
    local a = {}
    for i = 1, #raw do a[i] = clamp(raw[i] + k, 5, 99) end
    return PD.formulaArr(a, pos, 1)
  end
  local lo, hi = -80, 99
  for _ = 1, 24 do
    if hi - lo <= 1 then break end
    local mid = floor((lo + hi) / 2)
    if ovrAt(mid) >= ovr then hi = mid else lo = mid end
  end
  local a = {}
  for i = 1, #raw do a[i] = clamp(raw[i] + hi, 5, 99) end
  return a
end
local function packA(a) local d = {} for i = 1, #a do d[i] = string.format("%02d", (a[i] or 50) % 100) end return table.concat(d) end
local function unpackA(s)
  s = tostring(s or "")
  local a = {}
  for i = 1, floor(#s / 2) do a[i] = tonumber(s:sub(2 * i - 1, 2 * i)) or 50 end
  return #a > 0 and a or nil
end
--- The card's faces of attribute array `a` (PlayerDev.ATTRS order): { { label, value } x 6 } (keeper faces for a keeper).
function PRO.faces(a, gk)
  local PD = PDm()
  local out = {}
  if not (PD and a) then return out end
  local ix = {}
  for i, n in ipairs(PD.ATTRS) do ix[n] = i end
  local function mean(names) local s = 0 for _, n in ipairs(names) do s = s + (a[ix[n]] or 50) end return floor(s / #names + 0.5) end
  if gk then for _, f in ipairs(GKFACE) do out[#out + 1] = { f[1], mean(f[2]) } end
  else for _, k in ipairs(PRO.FOCUS) do out[#out + 1] = { PRO.FOCUS_LABEL[k], mean(FACE[k]) } end end
  return out
end

------------------------------------------------------------------------ faces
-- PRISM_PRO_FACES.tones[t] is "<id>:<club> ..." (PrismProFaces.lua); parsed once per tone.
local FACES_PER_SET = 40
PRO.FACES_PER_SET = FACES_PER_SET
local function toneList(t)
  G.tones = G.tones or {}
  if G.tones[t] then return G.tones[t] end
  local T = rawget(_G, "PRISM_PRO_FACES")
  local list = {}
  local s = type(T) == "table" and type(T.tones) == "table" and T.tones[t]
  if s then for id, club in tostring(s):gmatch("(%d+):(%d+)") do list[#list + 1] = { id = tonumber(id), club = tonumber(club) } end end
  G.tones[t] = list
  return list
end
function PRO.toneLabels()
  local T = rawget(_G, "PRISM_PRO_FACES")
  return type(T) == "table" and T.labels or { "Any" }
end
--- The body for skin tone `tone`, face set `set` and face `face` (wrapping round the tone's list): { id, club }, or nil.
function PRO.faceAt(tone, set, face)
  local list = toneList(tonumber(tone) or 1)
  if #list == 0 then return nil end
  local i = ((tonumber(set) or 1) - 1) * FACES_PER_SET + (tonumber(face) or 1)
  return list[(i - 1) % #list + 1]
end
-- A body's database row (name, nationality, jersey): read once from the club's engine lineup, kept for the session.
local function bodyRow(body, svc)
  if not body then return nil end
  G.rows = G.rows or {}
  local club = G.rows[body.club]
  if club == nil and svc and svc.GetCurrentPlayerLineup then
    local ok, rows = pcall(svc.GetCurrentPlayerLineup, 0, body.club, 0)
    club = {}
    if ok and type(rows) == "table" then for _, r in ipairs(rows) do local id = tonumber(r.CARD_ID or r.playerID); if id then club[id] = r end end end
    G.rows[body.club] = club
  end
  return club and club[body.id] or nil
end
local function bodyBio(id, svc)
  local NPD = rawget(_G, "NativePlayerData")
  if not (NPD and NPD.GetPlayerBio) then return nil end
  local ok, bio = pcall(NPD.GetPlayerBio, svc, id)
  return ok and type(bio) == "table" and bio or nil
end

------------------------------------------------------------------------ the 3D preview (slot 4)
local function p3d(action)
  local f = rawget(_G, "F16_SVC")
  if not (f and f.Cmd) then return false end
  return (pcall(f.Cmd, string.format("pc3d:slot:%d:%s", PRO.SLOT, action)))
end
function PRO.show3d(id, club, gk)
  id = tonumber(id)
  if not id or id <= 0 then return false end
  G.shown3d = p3d(string.format("show:%d:%d:%d", id, tonumber(club) or 0, gk and 2 or 0))
  return G.shown3d
end
function PRO.hide3d()
  if not G.shown3d then return end
  p3d("hide"); p3d("cleanup")
  G.shown3d = false
end

------------------------------------------------------------------------ Create Your Player
-- Rows: label, description, values { text, value } (the Popup "setup" mode's DEF format).
local function range(a, b, step, fmt)
  local out = {}
  for v = a, b, step or 1 do out[#out + 1] = { string.format(fmt or "%d", v), v } end
  return out
end
local FOCUS_VALUES = { { "Weak", -2 }, { "Below Average", -1 }, { "Balanced", 0 }, { "Strong", 1 }, { "Elite", 2 } }
local function creatorDef()
  local pos = {}
  for _, p in ipairs(PRO.POSITIONS) do pos[#pos + 1] = { p[1], p[2] } end
  local tones = {}
  for i, l in ipairs(PRO.toneLabels()) do tones[#tones + 1] = { l, i } end
  local sets = {}
  for i = 1, 60 do sets[i] = { "Set " .. i, i } end
  local focusDesc = "Where the attribute points go. A strength is paid for in the other areas: the overall stays the starting level you chose."
  return {
    pos = { "Position", "Your position on the pitch. The manager picks you for your line: keepers, defenders, midfielders or forwards.", pos },
    age = { "Age", "How old you are on day one. Young players grow the most; past 29 the decline starts.", range(16, 30) },
    ovr = { "Starting Level", "Your overall rating on day one. Start low and earn your place, or arrive as a finished player.", range(45, 80, 5, "%d OVR") },
    pot = { "Potential", "The highest overall you can grow into. Growth comes from playing time, form and training.", range(65, 95, 5, "%d POT") },
    pac = { "Pace", focusDesc, FOCUS_VALUES }, sho = { "Shooting", focusDesc, FOCUS_VALUES },
    pas = { "Passing", focusDesc, FOCUS_VALUES }, dri = { "Dribbling", focusDesc, FOCUS_VALUES },
    def = { "Defending", focusDesc, FOCUS_VALUES }, phy = { "Physical", focusDesc, FOCUS_VALUES },
    tone = { "Skin Tone", "Narrows the faces to one skin tone.", tones },
    face = { "Face", "Your face, hair and build: every face is a real player model, the same one you see in matches.", range(1, FACES_PER_SET) },
    set = { "More Faces", "Another set of " .. FACES_PER_SET .. " faces of the same skin tone.", sets },
  }
end
PRO.CREATOR_TABS = { { "Player", { "pos", "age", "ovr", "pot" } }, { "Attack", { "pac", "sho", "pas", "dri" } },
  { "Defence", { "def", "phy" } }, { "Look", { "tone", "face", "set" } } }
PRO.CREATOR_DEFAULTS = { pos = 25, age = 17, ovr = 60, pot = 85, pac = 0, sho = 0, pas = 0, dri = 0, def = 0, phy = 0, tone = 2, face = 1, set = 1 }

local function focusOf(c) local f = {} for _, k in ipairs(PRO.FOCUS) do f[k] = tonumber(c[k]) or 0 end return f end
local function seedOf(c) return 1 + ((tonumber(c.pos) or 0) * 7919 + (tonumber(c.tone) or 0) * 104729 + (tonumber(c.set) or 0) * 1299709 + (tonumber(c.face) or 0) * 15485863) % 999983 end

--- Opens Create Your Player on `popup` (an FCPopup) for club `club` (`clubName` is shown under the rows). `svc` is the
--- SquadMgtService (the faces' names and heights). done(build) with the chosen build, done(nil) after Back. Without the
--- native screens the default build with the first face is used at once.
function PRO.open(popup, svc, club, clubName, done)
  local PS = rawget(_G, "PrismSetup")
  local native = PS and PS.native and PS.native()
  local function build(c)
    local body = PRO.faceAt(c.tone, c.set, c.face)
    if not body then return nil end
    local ovr = tonumber(c.ovr) or 60
    return { body = body, pos = tonumber(c.pos) or 25, age = tonumber(c.age) or 17, ovr = ovr, pot = max(tonumber(c.pot) or 85, ovr),
             focus = focusOf(c), seed = seedOf(c) }
  end
  if not native or type(popup) ~= "table" or type(popup.showScreen) ~= "function" then
    local b = build(PRO.CREATOR_DEFAULTS)
    log("create: no native screens, the default build" .. (b and (" with body " .. b.body.id) or " (no faces)"))
    if done then done(b) end
    return false
  end
  local spec = {
    def = creatorDef(), tabs = PRO.CREATOR_TABS, defaults = PRO.CREATOR_DEFAULTS, choices = PRO.CREATOR_DEFAULTS,
    title = "Create Your Player", go = "Start Career", reset = "Reset", club = clubName, pro = true,
    text = "Create Your Player needs the native screens.",
  }
  spec.describe = function(key, c)
    local b = build(c)
    local lines = {}
    if b then
      local a = PRO.attrs(b.pos, b.ovr, b.focus, b.seed)
      local pn = POSNAME[b.pos] or "ST"
      lines[#lines + 1] = string.format("%s  ·  %d %s  ·  %d %s  ·  %s %d", pn, b.ovr, tr("OVR"), b.pot, tr("POT"), tr("Age"), b.age)
      local f = PRO.faces(a, b.pos == 0)
      local parts = {}
      for _, x in ipairs(f) do parts[#parts + 1] = x[1] .. " " .. x[2] end
      lines[#lines + 1] = table.concat(parts, "   ")
      local row = bodyRow(b.body, svc)
      local bio = bodyBio(b.body.id, svc)
      local who = row and row.playerName or ("#" .. b.body.id)
      local h = bio and tonumber(bio.height)
      lines[#lines + 1] = tr("Face") .. ": " .. tostring(who) .. ((h and h >= 140 and h <= 215) and string.format("  ·  %.2f m", h / 100) or "")
    end
    local d = creatorDef()[key]
    lines[#lines + 1] = ""
    lines[#lines + 1] = d and tr(d[2]) or ""
    return d and d[1] or "", table.concat(lines, "\n")
  end
  spec.onChange = function(c, key)
    if key ~= nil and key ~= "tone" and key ~= "face" and key ~= "set" and key ~= "pos" then return end
    local body = PRO.faceAt(c.tone, c.set, c.face)
    if body then PRO.show3d(body.id, club, tonumber(c.pos) == 0) end
  end
  popup:showScreen("setup", spec, function(n)
    PRO.hide3d()
    if n == 100 and type(spec.result) == "table" then
      local b = build(spec.result)
      if b then log(string.format("create: body %d (club %d), %s, age %d, %d/%d", b.body.id, b.body.club, POSNAME[b.pos] or "?", b.age, b.ovr, b.pot)) end
      if done then done(b) end
    elseif done then done(nil) end
  end)
  return true
end

-- A jersey number for the pro at `club`: his position's classic numbers first, else the first free one.
local function freeNumber(club, pos)
  local used = {}
  local s = sv()
  local cache = s and s.get and s.get("TeamCachedData")
  local e = type(cache) == "table" and cache[club]
  for _, r in ipairs(type(e) == "table" and type(e.players) == "table" and e.players or {}) do
    local n = tonumber(r.jerseyNumber); if n then used[n] = true end
  end
  local PD = PDm()
  local grp = PD and PD.GROUP and PD.GROUP[pos] or "ST"
  local pref = ({ GK = { 1, 13, 25 }, CB = { 4, 5, 15 }, FB = { 2, 3, 12 }, WB = { 2, 3, 22 }, CDM = { 6, 16 }, CM = { 8, 14, 18 },
                  CAM = { 10, 20 }, WM = { 7, 11, 17 }, W = { 7, 11, 19 }, CF = { 10, 9, 19 }, ST = { 9, 19, 29 } })[grp] or {}
  for _, n in ipairs(pref) do if not used[n] then return n end end
  for n = 2, 99 do if not used[n] then return n end end
  return 99
end

--- A new player career's way in, at TeamSelect's last boot step (`ts` is the TeamSelect screen: nav, api, loc; its
--- sessionVars are the career's). The user creates a player or picks one of the club's squad; either way the boot ends
--- with evt_team_select. Returns true when PrismPro took over the step (false: the stock PlayerSelector runs).
function PRO.start(ts, sessionVars)
  if type(ts) ~= "table" or type(ts.nav) ~= "table" then return false end
  local FCP = rawget(_G, "PRISM_FCPOPUP")
  if not (FCP and FCP.new) then return false end
  local okP, popup = pcall(FCP.new, FCP, { nav = ts.nav })
  if not okP or not popup then return false end
  if type(sessionVars) == "table" then G.sv = sessionVars end
  local s = sv()
  if not (s and s.set) then return false end
  -- a new career: the last career's pro is not this one's
  s.set(PRO.KEY, nil)
  local club = tonumber(rawget(_G, "currentSelectedTeamID"))
  local okS, svc = pcall(ts.api, "SquadMgtService")
  svc = okS and svc or nil
  local clubName = ""
  if ts.loc and club then local okN, n = pcall(ts.loc.LocalizeString, "TeamName_Abbr15_" .. club); if okN and n then clubName = n end end
  local function enter()
    ts.nav.Event(nil, "evt_team_select")
    ts.nav.Event(nil, "evt_hide_overlay", {})
  end
  local function squadPlayer()
    ts.nav.Event(nil, "evt_show_overlay", { vvm = "/flows/mainflow/gamemodes/Liga/Screens/PlayerCareer/PlayerSelector/PlayerSelector.vvm", data = { nav = ts.nav } })
  end
  local ask
  local function create()
    PRO.open(popup, svc, club, clubName, function(b)
      if not b then ask(); return end
      local PD = PDm()
      local td = today() or 0
      local seed = b.seed
      local st = { v = PRO.VERSION, id = b.body.id, kind = "new", club = club, org = b.body.club, pos = b.pos, age = b.age,
                   ovr = b.ovr, pot = b.pot, seed = seed, focus = b.focus, pending = true,
                   b = td - floor((b.age + 0.5) * 365.2425) + (seed % 180) - 90, js = freeNumber(club, b.pos),
                   trust = 45, car = emptyStats(), sea = emptyStats(), season = seasonYear(), hist = {}, last = {} }
      local a = PRO.attrs(b.pos, b.ovr, b.focus, seed)
      st.a0 = a and packA(a) or nil
      save(st)
      s.set("PlayerCareerPlayerID", st.id)
      enter()
    end)
  end
  ask = function()
    -- a player career needs a player: Back asks again
    popup:getResponse("How do you want to start your player career?", { "Create Your Player", "Play as a Squad Player" }, function(n)
      if n == 1 then create() elseif n == 2 then squadPlayer() else ask() end
    end)
  end
  ask()
  return true
end

------------------------------------------------------------------------ the hub
-- Puts the build into PlayerDev: the pro's attributes, position, potential and birth, overall from the formula.
local function applyBuild(st, p)
  local PD = PDm()
  local a = unpackA(st.a0) or PRO.attrs(st.pos, st.ovr, st.focus, st.seed)
  if not (PD and p and a) then return false end
  p.a = { unpack(a) }; p.s = { unpack(a) }
  p.pos, p.ir, p.off, p.birth = st.pos, 1, 0, st.b
  p.ovr = PD.formulaArr(p.a, p.pos, 1); p.so = p.ovr
  p.pot = max(st.pot, p.ovr); p.cap = p.pot
  return true
end
-- Finishes a created player at the hub: the body joins the club (PrismYouth), PlayerDev tracks him with the build.
local function finish(st)
  local Y, PD, CD = Ym(), PDm(), rawget(_G, "CareerDev")
  if not (Y and Y.adoptPro and PD) then log("create: PrismYouth / PlayerDev missing, the build waits"); return false end
  local club = tonumber(st.club) or tonumber(rawget(_G, "currentSelectedTeamID"))
  local y, err = Y.adoptPro(st.id, st.org, club, st.b, st.pos, st.pot, st.ovr, st.seed, st.js)
  if not y then log("create: " .. tostring(err)); return false end
  local p = PD.get(st.id)
  if not p and CD and CD.ensure then p = CD.ensure(st.id, club) end
  if not p then
    -- the database row could not be read (no F16Service): every attribute differs from a zero base, so the match
    -- override table carries them all (as PrismYouth.pdLike does)
    local named = {}
    for i, n in ipairs(PD.ATTRS) do named[n] = (unpackA(st.a0) or {})[i] end
    p = PD.track(st.id, { pos = st.pos, ir = 1, birth = st.b, pot = st.pot, ovr = st.ovr, attrs = named, team = club })
    local zero = {}
    for i = 1, #PD.ATTRS do zero[i] = 0 end
    p.b, p.ovr0 = zero, 0
  end
  applyBuild(st, p)
  if Y.refreshRow then
    local s = sv()
    local cache = s and s.get("TeamCachedData")
    local e = type(cache) == "table" and cache[club]
    for _, r in ipairs(type(e) == "table" and type(e.players) == "table" and e.players or {}) do
      if tonumber(r.CARD_ID) == st.id then pcall(Y.refreshRow, r) end
    end
  end
  st.pending = nil
  log(string.format("create: %s is at club %d (%s, %d OVR, %d POT)", tostring(y.nm or st.id), club, POSNAME[st.pos] or "?", p.ovr, p.pot))
  if CD and CD.overridesStale then pcall(CD.overridesStale) end
  return true
end

--- The hub binds (MatchSelect, after CareerDev and PrismYouth): hands over sessionVars, the squad service and the hub's
--- localiser (club names for the offers), applies a pending build, and makes sure the pro's id and his PlayerDev record
--- are there. Does nothing outside a player career.
function PRO.bind(sessionVars, services, loc)
  if type(sessionVars) == "table" then G.sv = sessionVars end
  if type(services) == "table" then G.svc = services.SquadMgtService or services.SquadManagementService or G.svc end
  if loc ~= nil then G.loc = loc end
  G.idle = 0
  if not PRO.active() then return end
  local s = sv()
  local st = state()
  if not st then
    -- the stock way in (a squad player from PlayerSelector): his career starts here
    local id = tonumber(s.get("PlayerCareerPlayerID"))
    if not id then return end
    st = { v = PRO.VERSION, id = id, kind = "squad", club = tonumber(rawget(_G, "currentSelectedTeamID")), trust = 50,
           car = emptyStats(), sea = emptyStats(), season = seasonYear(), hist = {}, last = {} }
    save(st)
    log("career: squad player " .. id)
  end
  if st.pending then pcall(finish, st) end
  s.set("PlayerCareerPlayerID", st.id)
  -- the development state lost him (an older save): the build again, or his database values for a squad player
  local PD, CD = PDm(), rawget(_G, "CareerDev")
  if PD and not st.pending and not PD.get(st.id) and CD and CD.ensure then
    local p = CD.ensure(st.id, tonumber(rawget(_G, "currentSelectedTeamID")))
    if p and st.kind == "new" then applyBuild(st, p) end
  end
end

------------------------------------------------------------------------ manager trust and the team sheet
local ROLES = { { 80, "Key Player" }, { 62, "First Team" }, { 45, "Rotation" }, { 30, "Squad Player" }, { 0, "Fringe Player" } }
function PRO.trust() local st = state(); return st and clamp(tonumber(st.trust) or 50, 0, 100) or 50 end
function PRO.role() local t = PRO.trust(); for _, r in ipairs(ROLES) do if t >= r[1] then return r[2] end end return "Fringe Player" end
local function moveTrust(st, d) st.trust = clamp((tonumber(st.trust) or 50) + d, 0, 100) end

local LINE = { GK = 1, CB = 2, LB = 2, RB = 2, LWB = 2, RWB = 2, SW = 2, LCB = 2, RCB = 2,
  CM = 3, CDM = 3, CAM = 3, LM = 3, RM = 3, LCM = 3, RCM = 3, LDM = 3, RDM = 3, LAM = 3, RAM = 3,
  ST = 4, CF = 4, LW = 4, RW = 4, LF = 4, RF = 4, LS = 4, RS = 4 }
--- The chance (0..1) the AI manager starts the pro in a match: his trust, less when more fit players of his line than it
--- has places are rated above him (a doubt the trust itself takes away: a fully trusted player starts anyway), more in
--- a rotation match (`rotation`: PlayerCareer's "weak" team sheet, the fringe players' chance).
function PRO.startChance(above, slots, rotation)
  local t = PRO.trust()
  local base = (t - 15) / 70
  if above >= slots then base = base - 0.25 * (above - slots + 1) * (1 - t / 100) end
  if rotation then base = max(base, 0.85) end
  return clamp(base, 0.04, 0.97)
end
--- PlayerCareer's pickAISquad calls this with its starting XI and bench (row lists), the fit players and the team
--- sheet's mode ("strong" / "balanced" / "weak"): the manager's trust decides whether the pro starts, is benched, or
--- stays out. Swaps within the pro's line only (never a keeper for an outfield player). Changes the lists in place.
--- `rnd` (tests) replaces math.random.
function PRO.adjustXI(starting11, bench, eligible, mode, rnd)
  local id = PRO.id()
  if not id or type(starting11) ~= "table" then return end
  rnd = rnd or math.random
  local me
  for _, p in ipairs(eligible or {}) do if tonumber(p.CARD_ID) == id then me = p; break end end
  if not me then return end   -- suspended or injured: he cannot play
  local line = LINE[tostring(me.position)] or (me.isGoalie and 1) or 3
  local inXI, onBench
  local slots, above = 0, 0
  for i, p in ipairs(starting11) do
    if tonumber(p.CARD_ID) == id then inXI = i end
    if (LINE[tostring(p.position)] or 3) == line then slots = slots + 1 end
  end
  for i, p in ipairs(bench or {}) do if tonumber(p.CARD_ID) == id then onBench = i end end
  for _, p in ipairs(eligible) do
    if tonumber(p.CARD_ID) ~= id and (LINE[tostring(p.position)] or 3) == line and (p.rating or 0) > (me.rating or 0) then above = above + 1 end
  end
  if slots == 0 then slots = 1 end
  local want = rnd() < PRO.startChance(above, slots, mode == "weak")
  if want and not inXI then
    -- the weakest starter of his line makes room (to the bench)
    local out, low = nil, math.huge
    for i, p in ipairs(starting11) do
      if (LINE[tostring(p.position)] or 3) == line and (p.rating or 0) < low then out, low = i, (p.rating or 0) end
    end
    if not out then return end
    local displaced = starting11[out]
    starting11[out] = me
    if onBench then bench[onBench] = displaced
    else
      -- nobody leaves the squad: a full bench's weakest player ends up 8th, which is the reserves' first place
      bench[#bench + 1] = displaced
      table.sort(bench, function(x, y) return (x.rating or 0) > (y.rating or 0) end)
    end
  elseif not want and inXI then
    -- the best of his line not starting takes his place; he goes to the bench
    local inn, best, fromBench = nil, -1, false
    for i, p in ipairs(bench or {}) do
      if (LINE[tostring(p.position)] or 3) == line and (p.rating or 0) > best then inn, best, fromBench = i, (p.rating or 0), true end
    end
    if not inn then return end
    starting11[inXI] = bench[inn]
    bench[inn] = me
  end
end

------------------------------------------------------------------------ matches
-- The day ("DD/MM/YY") and the score from the pro's side.
local function result(mine, hg, ag, home)
  local gf, ga = (mine == home) and hg or ag, (mine == home) and ag or hg
  return (gf > ga and "W" or gf < ga and "L" or "D") .. " " .. gf .. "-" .. ga, gf, ga
end
--- CareerDev.recordMatch calls this after every recorded match (played or simulated). `rows` are its player rows
--- { id, team, mins, goals, assists, yc, rc, rating? }, `ratings` PlayerDev's { [id] = rating }.
function PRO.onMatch(home, away, hg, ag, rows, ratings, motm, sim)
  local id = PRO.id()
  local st = id and state()
  if not st then return end
  local r
  for _, x in ipairs(rows or {}) do if tonumber(x.id) == id then r = x; break end end
  local club = r and tonumber(r.team) or tonumber(rawget(_G, "currentSelectedTeamID"))
  if not (club == home or club == away) then return end
  local res, gf, ga = result(club, tonumber(hg) or 0, tonumber(ag) or 0, home)
  local mins = r and (tonumber(r.mins) or 90) or 0
  local rating = r and tonumber(ratings and ratings[id] or r.rating) or nil
  if mins > 0 then
    -- a simulated match's rows say when he came on (0: from the start); a played match's rows say only the minutes
    local started = (r.on ~= nil and tonumber(r.on) == 0) or (r.on == nil and mins >= 60)
    for _, t in ipairs({ st.car, st.sea }) do
      t.apps = t.apps + 1; t.mins = t.mins + mins
      if started then t.starts = t.starts + 1 end
      t.goals = t.goals + (tonumber(r.goals) or 0); t.assists = t.assists + (tonumber(r.assists) or 0)
      if motm == id then t.motm = t.motm + 1 end
      if ga == 0 and mins >= 60 and (st.pos or 25) <= 8 then t.cs = t.cs + 1 end
      if rating then t.rs = t.rs + rating; t.rn = t.rn + 1 end
    end
    -- the manager's trust follows the rating (scaled by the minutes), the award and a red card
    local d = rating and clamp((rating - 6.6) * 6, -8, 10) * min(1, mins / 90) or 0
    if motm == id then d = d + 4 end
    if (tonumber(r.rc) or 0) > 0 then d = d - 6 end
    moveTrust(st, d)
  end
  local opp = (club == home) and away or home
  table.insert(st.last, 1, { d = tostring(rawget(_G, "GLOBAL_DATE_PLACEHOLDER") or ""), opp = opp, r = rating and floor(rating * 10 + 0.5) / 10 or nil,
    g = r and (tonumber(r.goals) or 0) or 0, a = r and (tonumber(r.assists) or 0) or 0, m = mins, res = res, sim = sim and true or nil })
  for i = #st.last, 11, -1 do st.last[i] = nil end
  save(st)
end
--- The month tick (CareerDev.onDate's first day of a month): trust drifts towards what the pro's overall is worth in
--- his squad: the best of his line are trusted more, a player rated below most of his line less.
function PRO.onMonth()
  local id = PRO.id()
  local st = id and state()
  if not st then return end
  local s = sv()
  local cache = s and s.get("TeamCachedData")
  local e = type(cache) == "table" and cache[tonumber(rawget(_G, "currentSelectedTeamID"))]
  local rows = type(e) == "table" and e.players or {}
  local me
  for _, r in ipairs(rows) do if tonumber(r.CARD_ID) == id then me = r end end
  if not me then return end
  local line = LINE[tostring(me.position)] or 3
  local above, n = 0, 0
  for _, r in ipairs(rows) do
    if tonumber(r.CARD_ID) ~= id and (LINE[tostring(r.position)] or 3) == line then
      n = n + 1
      if (r.rating or 0) > (me.rating or 0) then above = above + 1 end
    end
  end
  local worth = clamp(85 - above * (n > 6 and 9 or 13), 20, 85)
  moveTrust(st, (worth - st.trust) * 0.15)
  save(st)
end
--- A season ended: the season's line goes into the history and the season's counts start again.
function PRO.onSeasonEnd()
  local st = PRO.id() and state()
  if not st then return end
  local sea = st.sea or emptyStats()
  local PD = PDm()
  st.hist[#st.hist + 1] = { y = st.season, club = tonumber(rawget(_G, "currentSelectedTeamID")), apps = sea.apps, goals = sea.goals,
    assists = sea.assists, avg = sea.rn > 0 and floor(sea.rs / sea.rn * 100 + 0.5) / 100 or nil, ovr = PD and PD.ovrOf(st.id) or nil }
  st.sea = emptyStats()
  st.season = (tonumber(st.season) or seasonYear()) + 1
  save(st)
end
--- A summary of the pro's career for screens: { name, role, trust, car, sea, avg, seasonAvg, last, hist }.
function PRO.summary()
  local st = PRO.id() and state()
  if not st then return nil end
  local function avg(t) return t.rn > 0 and floor(t.rs / t.rn * 100 + 0.5) / 100 or nil end
  return { id = st.id, role = PRO.role(), trust = floor(PRO.trust() + 0.5), car = st.car, sea = st.sea, avg = avg(st.car),
           seasonAvg = avg(st.sea), last = st.last, hist = st.hist }
end

------------------------------------------------------------------------ offers
local function teamName(loc, id)
  if loc and id then local ok, n = pcall(loc.LocalizeString, "TeamName_Abbr15_" .. id); if ok and n and n ~= "" then return n end end
  return "Club " .. tostring(id)
end
-- The question about offer `o` (whole sentences, so the variant's templates translate them).
local function offerText(o, loc)
  local who, role = teamName(loc, o.offeringClub), PRO.role()
  if o.isLoan and o.loanDuration then return string.format("%s want you on loan for %s months. Your role here: %s.", who, tostring(o.loanDuration), role) end
  if o.isLoan then return string.format("%s want you on loan. Your role here: %s.", who, role) end
  local fee = tonumber(o.priceTag) or 0
  local f = fee >= 1000000 and string.format("£%.1fM", fee / 1000000) or string.format("£%dK", floor(fee / 1000))
  return string.format("%s have made a %s offer for you. Your role here: %s.", who, f, role)
end
--- Asks about the pro's open offer on `owner`'s popup (the hub or one of its cards). Accept moves him (PlayerCareer:
--- acceptOffer; the career follows him to the new club), Reject drops it, Later keeps it for the My Offers card.
--- Returns whether there was an offer to ask about.
function PRO.offers(owner)
  local PC = rawget(_G, "g_PlayerCareer")
  local o = PC and PC.getOfferForMyPlayer and PC:getOfferForMyPlayer()
  local popup = type(owner) == "table" and owner.FCPopup or nil
  if not popup and type(owner) == "table" and type(owner.nav) == "table" then
    local FCP = rawget(_G, "PRISM_FCPOPUP"); if FCP and FCP.new then local ok, p = pcall(FCP.new, FCP, { nav = owner.nav }); if ok then popup = p end end
  end
  if not popup then return false end
  local loc = owner.loc or G.loc
  if not o then
    popup:getResponse("No club has made an offer for you. Keep playing well and they will come.", { "OK" }, function() end)
    return false
  end
  local key = tostring(o.offeringClub) .. ":" .. tostring(o.priceTag) .. ":" .. tostring(o.isLoan)
  G.asked[key] = true
  popup:getResponse(offerText(o, loc), { "Accept", "Reject", "Later" }, function(n)
    if n == 1 then
      local ok, moved, newTeam = pcall(PC.acceptOffer, PC)
      if ok and moved then
        local Y = Ym()
        if Y and Y.setProClub then pcall(Y.setProClub, PRO.id(), newTeam) end
        local st = state()
        if st then st.trust = 45; save(st) end
        log("offer accepted: to club " .. tostring(newTeam))
        if type(owner.nav) == "table" then owner.nav.Event(nil, "evt_reload") end
      else
        log("offer accept failed: " .. tostring(moved))
      end
    elseif n == 2 then
      pcall(PC.rejectOffer, PC)
      log("offer rejected")
    end
  end)
  return true
end
--- The hub's update (MatchSelect, every frame): once the hub has been idle for a moment, asks about a new offer for the
--- pro (once per offer in a session; the My Offers card asks again).
function PRO.step(hub)
  if type(hub) ~= "table" or not PRO.active() then return end
  if hub.isAnimating or hub.isAutoAdvancing then G.idle = 0; return end
  G.idle = (G.idle or 0) + 1
  if G.idle < 45 then return end
  G.idle = -600   -- checked again in ten seconds
  local PC = rawget(_G, "g_PlayerCareer")
  local o = PC and PC.getOfferForMyPlayer and PC:getOfferForMyPlayer()
  if not o then return end
  local key = tostring(o.offeringClub) .. ":" .. tostring(o.priceTag) .. ":" .. tostring(o.isLoan)
  if G.asked[key] then return end
  PRO.offers(hub)
end

------------------------------------------------------------------------ My Player
--- My Player: the Player Profile screen on the pro (the hub's card; `owner` is the hub's UI object).
function PRO.openProfile(owner)
  local id = PRO.id()
  local PP = rawget(_G, "PrismProfile")
  if not id then return false end
  if PP and PP.open then
    local ok, shown = pcall(PP.open, owner, { id }, 1, { teamId = tonumber(rawget(_G, "currentSelectedTeamID")), loc = owner and owner.loc })
    if ok and shown then return true end
  end
  -- no profile screen: a summary on the popup
  local S = PRO.summary()
  local FCP = rawget(_G, "PRISM_FCPOPUP")
  if S and FCP and type(owner) == "table" and type(owner.nav) == "table" then
    local okP, popup = pcall(FCP.new, FCP, { nav = owner.nav })
    if okP and popup then
      local c = S.car
      popup:getResponse(string.format("%s (trust %d). Career: %d apps, %d goals, %d assists%s.", S.role, S.trust, c.apps, c.goals, c.assists,
        S.avg and string.format(", average %.2f", S.avg) or ""), { "OK" }, function() end)
      return true
    end
  end
  return false
end

------------------------------------------------------------------------ save
--- The state for the career save (Serializer stores it as `pro`), nil outside a player career.
function PRO.serialize()
  if not PRO.active() then return nil end
  return state()
end
--- LoadSave: the saved state back into sessionVars, and the pro's id.
function PRO.restore(sessionVars, t)
  if type(sessionVars) == "table" then G.sv = sessionVars end
  if type(t) ~= "table" or not tonumber(t.id) then return false end
  t.car = type(t.car) == "table" and t.car or emptyStats()
  t.sea = type(t.sea) == "table" and t.sea or emptyStats()
  for _, k in ipairs({ "apps", "starts", "mins", "goals", "assists", "motm", "cs", "rs", "rn" }) do
    t.car[k] = tonumber(t.car[k]) or 0; t.sea[k] = tonumber(t.sea[k]) or 0
  end
  t.hist = type(t.hist) == "table" and t.hist or {}
  t.last = type(t.last) == "table" and t.last or {}
  t.focus = type(t.focus) == "table" and t.focus or {}
  t.id = tonumber(t.id)
  save(t)
  local s = sv()
  if s and s.set then s.set("PlayerCareerPlayerID", t.id) end
  return true
end

return PRO
