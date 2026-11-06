-- Host test for a created player's whole way in, on Lua 5.1 with the real PlayerDev, CareerDev, PrismYouth, PlayerCareer,
-- PrismPro and the ProName keyboard VM (the engine's reads and libpv's pro: commands are faked): the boot's choice, the
-- first name and surname typed on the keyboard, the player page and the face page with every Back, the hub applying
-- the build and writing the look, name and body into the database once, the squad row, the match override table, the
-- AI manager's team sheet, a save and a load.
-- usage: lua5.1 tests/test_flow.lua <ux dir>
local UX = arg[1] or "ux"
local D = UX .. "/flows/mainflow/gamemodes/Liga/Data/"
local pass, fail = 0, 0
local function ck(c, what) if c then pass = pass + 1 else fail = fail + 1; print("  FAIL  " .. what) end end

local data = {}
local SV = { get = function(k) return data[k] end, set = function(k, v) data[k] = v end }
rawset(_G, "CAREER_SESSION_VARS", SV)
GLOBAL_DATE_PLACEHOLDER = "01/07/25"
CAREER_FULL_YEAR = 2025
local USER, ORG = 10, 753
currentSelectedTeamID = USER

-- the engine: the user's club and the body's database club, and NativePlayerData's reads of the body (his host values)
local function row(id, pos, r, nm) return { CARD_ID = id, playerID = id, position = pos, rating = r, playerName = nm or ("P" .. id), jerseyNumber = id % 30 + 1, nationalityID = 54, isGoalie = pos == "GK" } end
local userRows = { row(1, "GK", 80), row(2, "CB", 75), row(3, "CB", 74), row(4, "LB", 72), row(5, "RB", 72), row(6, "CM", 76), row(7, "CM", 75),
  row(8, "CDM", 74), row(9, "LW", 78), row(10, "RW", 77), row(11, "ST", 79), row(12, "GK", 70), row(13, "CB", 69), row(14, "CM", 70),
  row(15, "ST", 71), row(16, "LB", 66), row(17, "RW", 68), row(18, "CDM", 67), row(19, "CB", 65), row(20, "CM", 64), row(21, "ST", 63), row(22, "LM", 62) }
data.TeamCachedData = { [USER] = { players = userRows, league = 13 } }
data.LeagueTeams = {}; data.currentUserLeagueID = 13
data.isSuspended = {}
local PD = dofile(D .. "PlayerDev.lua"); rawset(_G, "PlayerDev", PD)
dofile(D .. "PrismProLook.lua")
local L = rawget(_G, "PRISM_PRO_LOOK")
local BODY = 243893
L.bodies = BODY .. ":" .. ORG .. " 7001:" .. USER   -- the second is at the user's club: never chosen
local PRO = dofile(D .. "PrismPro.lua")
PRO.G.bodies = nil
data.TeamCachedData[ORG] = { players = { row(BODY, "CM", 58, "Body Guy") }, league = 99 }
local hostAttrs = {}
for _, n in ipairs(PD.ATTRS) do hostAttrs[n] = 55 end
hostAttrs.preferredPosition1 = 14
rawset(_G, "NativePlayerData", {
  GetPlayerAttributes = function(_, id) local t = {}; for k, v in pairs(hostAttrs) do t[k] = v end; return t end,
  GetPlayerBio = function(_, id) return { overallRating = 58, height = 181, weight = 75, preferredFoot = 1 } end,
  GetPlayerMeta = function() return { potential = 70, internationalReputation = 1 } end,
  GetBirthdateValue = function() return 151607 end,
})
function getCachedTeamPlayers(id) local e = data.TeamCachedData[id]; return e and e.players or false end
local CD = dofile(D .. "CareerDev.lua"); rawset(_G, "CareerDev", CD)
data.InPlayerCareerMode = true; data.InCareerMode = true
data._prismYouth = { v = 1, seed = 1, season = 0, hc = 1, reg = {}, ret = {}, spill = {}, bt = {} }
local Y = dofile(D .. "PrismYouth.lua"); rawset(_G, "PrismYouth", Y)
dofile(D .. "PrismSetup.lua")

-- libpv: the pro: commands as f16_pro answers them (the file's values change on pro:db / pro:name), everything else ""
local libpv = { sent = {}, caps = "pro:1", dbErr = nil, file = { height = 181 }, names = "Kenan||K. Fatkić|Fatkic", reply = "" }   -- the body's row in R98e's database
local function count(prefix) local n = 0 for _, c in ipairs(libpv.sent) do if c:sub(1, #prefix) == prefix then n = n + 1 end end return n end
local function lastSent(prefix) for i = #libpv.sent, 1, -1 do local c = libpv.sent[i]; if c:sub(1, #prefix) == prefix then return c end end end
rawset(_G, "F16_SVC", {
  Cmd = function(c)
    if c:sub(1, 4) ~= "log:" then libpv.sent[#libpv.sent + 1] = c end
    local r = ""
    if c == "pro:caps" then r = libpv.caps
    elseif c:match("^pro:look:") then r = "ok:19"
    elseif c:match("^pro:get:") then r = "height=181,weight=75;" .. libpv.names
    elseif c:match("^pro:db:") then
      if libpv.dbErr then r = "err:" .. libpv.dbErr
      else
        local n = 0
        for k, v in c:match("^pro:db:%d+:(.*)$"):gmatch("(%w+)=(%d+)") do if libpv.file[k] ~= v then libpv.file[k] = v; n = n + 1 end end
        r = n > 0 and ("ok:changed=" .. n) or "ok:same"
      end
    elseif c:match("^pro:name:") then
      local nm = c:match("^pro:name:%d+:(.*)$")
      r = nm ~= libpv.names and "ok:changed" or "ok:same"; libpv.names = nm
    end
    libpv.reply = r
  end,
  Out = function() return libpv.reply end,
})

-- the ProName keyboard VM, as the overlay runs it (its skin wrap left out: the skin only draws)
local ProName = assert(loadfile(UX .. "/flows/mainflow/gamemodes/Liga/Screens/ProName/ProName__ProName.lua"))(
  { wrap = function(C) return C end }, "theme", "spec")
local function keyboard(d)
  local im = { pub = {}, act = {}, sub = {} }
  function im.Subscribe(b, f) im.sub[b] = f end
  function im.Unsubscribe(b) im.sub[b] = nil end
  function im.Publish(b, v) im.pub[b] = v end
  function im.RegisterAction(a, f) im.act[a] = f end
  function im.UnregisterAction(a) im.act[a] = nil end
  local vm = ProName:new({ im = im, data = d })
  for _, f in pairs(im.sub) do f() end
  local k = { vm = vm, im = im }
  function k.type(text) for i = 1, #text do local c = text:sub(i, i); im.act[c == " " and "act_dot" or ("act_" .. c)]() end end
  function k.label() return im.pub.bnd_matchday_label end
  return k
end

print("== the keyboard: capitals, spaces, the limit, Back ==")
local events = {}
local navK = { Event = function(_, e) events[#events + 1] = e end }
local got, answers = nil, 0
local k = keyboard({ nav = navK, title = "Surname", crumb = "Create Your Player", text = "", max = 20, done = function(n) got = n; answers = answers + 1 end })
ck(k.im.pub.bnd_kb_title == "Surname" and k.im.pub.bnd_kb_crumb == "Create Your Player" and k.label() == "", "title, crumb, empty")
k.type(" da  silva")
ck(k.label() == "Da Silva", "a capital per word, no leading or double space: '" .. tostring(k.label()) .. "'")
k.im.act.act_backspace(); k.type("x")
ck(k.label() == "Da Silvx", "backspace")
k.im.act.act_delete()
ck(k.label() == "", "delete clears")
k.type("abcdefghijklmnopqrstuvwxyz")
ck(#k.label() == 20, "at most 20 letters: " .. #k.label())
k.im.act.act_delete(); k.type("oluwa ")
k.im.act.act_submit(); k.im.act.act_submit()
ck(got == "Oluwa" and answers == 1 and events[#events] == "evt_hide_overlay", "Enter: the overlay closes, one answer, the space trimmed")
got = "x"
local k2 = keyboard({ nav = navK, text = "", done = function(n) got = n end })
k2.im.act.act_submit()
ck(got == nil, "Enter on an empty name is Back")
local k3 = keyboard({ nav = navK, text = "Davun", done = function() end })
ck(k3.label() == "Davun" and k3.im.pub.bnd_kb_title == "Player Name", "the name so far is kept, the default title")
k3.vm:finalize()
ck(next(k3.im.act) == nil and next(k3.im.sub) == nil, "finalize leaves no action or binding behind")

print("== TeamSelect's last step: the choice, the names, the two pages ==")
local overlays, popups = {}, {}
events = {}
local nav = { Event = function(_, e, d)
  events[#events + 1] = e .. ((d and d.vvm) and (" " .. d.vvm:match("([^/]+)%.vvm$")) or "")
  if e == "evt_show_overlay" and d and d.vvm and d.vvm:find("ProName", 1, true) then overlays[#overlays + 1] = d.data end
end }
local function lastName() return overlays[#overlays] end
local function typeName(text) local kb = keyboard(lastName()); kb.im.act.act_delete(); kb.type(text); kb.im.act.act_submit() end
local FCP = {}
FCP.__index = FCP
function FCP.new(cls, init) return setmetatable({ nav = init.nav }, cls) end
function FCP:getResponse(msg, btn, cb) popups[#popups + 1] = { msg = msg, btn = btn, cb = cb } end
function FCP:showScreen(mode, spec, cb) popups[#popups + 1] = { mode = mode, spec = spec, cb = cb } end
rawset(_G, "PRISM_FCPOPUP", FCP)
rawset(_G, "PrismSetup", setmetatable({ native = function() return true end }, { __index = rawget(_G, "PrismSetup") }))
local ts = { nav = nav, api = function(n) return { GetCurrentPlayerLineup = function(_, club) local e = data.TeamCachedData[club]; return e and e.players or {} end } end,
  loc = { LocalizeString = function(k) return "Club " .. k:match("(%d+)$") end } }
data._prismPro = { id = 1, kind = "new", look = {} }   -- the last career's pro: not this one's
ck(PRO.start(ts, SV) == true, "PrismPro takes the step")
ck(data._prismPro == nil, "the last career's pro is gone")
ck(popups[1] and popups[1].btn[1] == "Create Your Player" and popups[1].btn[2] == "Play as a Squad Player", "asks which way")
popups[1].cb(1)
ck(#overlays == 1 and lastName().title == "First Name" and lastName().text == "", "the first name keyboard opens")
-- Back on the first name asks the question again
keyboard(lastName()).im.act.act_submit()
ck(#popups == 2 and popups[2].btn and popups[2].btn[1] == "Create Your Player", "Back on the first name asks again")
popups[2].cb(1)
typeName("davun")
ck(#overlays == 3 and lastName().title == "Surname", "then the surname")
keyboard(lastName()).im.act.act_submit()
ck(#overlays == 4 and lastName().title == "First Name" and lastName().text == "Davun", "Back on the surname: the first name again, as typed")
typeName("davun")
typeName("oluwa")
local p1 = popups[#popups]
ck(p1.mode == "setup" and p1.spec.title == "Create Your Player" and p1.spec.club == "Club 10" and p1.spec.pro == true and p1.spec.zoom == nil, "the player page opens")
ck(select(2, p1.spec.describe("pos", p1.spec.choices)):find("Davun Oluwa", 1, true), "the player page knows his name")
p1.cb(0)
ck(#overlays == 6 and lastName().title == "Surname" and lastName().text == "Oluwa", "Back on the player page: the surname again")
typeName("oluwa")
p1 = popups[#popups]
local c1 = {}
for kk, v in pairs(p1.spec.choices) do c1[kk] = v end
c1.pos, c1.age, c1.ovr, c1.pot, c1.sho, c1.pac, c1.height, c1.weight, c1.foot = 25, 17, 60, 88, 2, 1, 191, 84, 2
p1.spec.result = c1
p1.cb(100)
local p2 = popups[#popups]
ck(p2.mode == "setup" and p2.spec.title == "Create Your Face" and p2.spec.go == "Start Career" and p2.spec.zoom == "face", "the face page opens")
ck(select(2, p2.spec.describe("head", p2.spec.choices)):find("191 cm  ·  84 kg  ·  Left", 1, true), "the face page knows the player page")
p2.cb(0)
local p1b = popups[#popups]
ck(p1b.spec.title == "Create Your Player" and p1b.spec.choices.height == 191 and p1b.spec.choices.foot == 2, "Back on the face page: the player page as it was left")
p1b.spec.result = p1b.spec.choices
p1b.cb(100)
p2 = popups[#popups]
local c2 = {}
for kk, v in pairs(p2.spec.choices) do c2[kk] = v end
c2.head, c2.tone, c2.eyes, c2.brow, c2.beard, c2.hair, c2.hairColour, c2.boots = L.heads[5], L.tones[3], L.eyes[2], L.brows[1], L.beards[3], L.hairs[40], 3, L.shoes[7]
p2.spec.result = c2
p2.cb(100)
local st = data._prismPro
ck(st and st.pending and st.id == BODY and st.kind == "new" and st.org == ORG, "the build waits for the hub, on the free body")
ck(st.first == "Davun" and st.sur == "Oluwa" and type(st.last) == "table" and PRO.fullName(st) == "Davun Oluwa", "his names (the match list apart)")
ck(st.pos == 25 and st.pot == 88 and st.height == 191 and st.weight == 84 and st.foot == 2, "the player page")
ck(st.look.head == L.heads[5] and st.look.hair == L.hairs[40] and st.look.hairColour == 3 and st.look.boots == L.shoes[7] and st.look.beard == L.beards[3], "the face page")
ck(data.PlayerCareerPlayerID == BODY, "PlayerCareerPlayerID is the body")
ck(events[#events - 1] == "evt_team_select" and events[#events] == "evt_hide_overlay", "the boot goes on to the hub")
ck(st.js and st.js >= 1 and st.js <= 99, "a jersey number: " .. tostring(st.js))
local age = (PD.dayOfCareer("01/07/25") - st.b) / 365.2425
ck(age > 16.5 and age < 18, "born 17 years ago: " .. tostring(age))
ck(count("pro:db:") == 0 and count("pro:name:") == 0, "nothing is written before the hub")

print("== the hub binds: the body joins the club with the build, the database gets his look and name ==")
libpv.sent = {}
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(st.pending == nil, "applied")
local y = Y.get(BODY)
ck(y and y.k == "C" and y.club == USER and y.nm == "Davun Oluwa" and y.p == 25 and y.t == 88, "a youth of the user's club: " .. tostring(y and y.nm))
local mine
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID == BODY then mine = r end end
ck(mine and mine.position == "ST" and mine.playerName == "Davun Oluwa" and mine.rating == 60, "his squad row: " .. tostring(mine and mine.playerName) .. " " .. tostring(mine and mine.rating))
local inOrg = false
for _, r in ipairs(data.TeamCachedData[ORG].players) do if r.CARD_ID == BODY then inOrg = true end end
ck(not inOrg, "he left his database club")
local p = PD.get(BODY)
ck(p and p.ovr == 60 and p.pos == 25 and p.pot == 88 and PD.formulaArr(p.a, 25, 1) == 60, "PlayerDev has the build")
ck(p and p.b and p.b[1] == 55, "the base is his host's database values (what the engine reads)")
local ov = CD.matchOverrides({ USER })
local n = 0
for _, e in ipairs(ov) do if e[1] == BODY then n = n + 1 end end
ck(n >= 25, "real matches get his build through the override table (" .. n .. " values)")
local want = PRO.fieldList(PRO.lookFields(st))
ck(lastSent("pro:look:") == "pro:look:" .. BODY .. ":" .. want, "the preview gets his look")
ck(want:find("headtypecode=" .. L.heads[5] .. ",", 1, true) and want:find("hairtypecode=" .. L.hairs[40] .. ",", 1, true) and want:find("height=191,weight=84,preferredfoot=2,preferredposition1=25", 1, true), "the fields: " .. want)
ck(lastSent("pro:db:") == "pro:db:" .. BODY .. ":" .. want, "the database file gets the same fields")
ck(lastSent("pro:name:") == "pro:name:" .. BODY .. ":Davun||D. Oluwa|Oluwa", "and his names, the surname column empty as in every row: " .. tostring(lastSent("pro:name:")))
ck(st.orig == "height=181,weight=75;Kenan||K. Fatkić|Fatkic", "the body's own values are kept first: " .. tostring(st.orig))
ck(st.restart == true and st.dbErr == nil, "a restart is due")
PRO.bind(SV, { SquadMgtService = {} }, nil)
local cnt = 0
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID == BODY then cnt = cnt + 1 end end
ck(cnt == 1, "binding again changes nothing")
ck(count("pro:db:") == 1 and count("pro:caps") == 1 and count("pro:look:") == 2, "the file is checked once a session; the preview gets the look every bind")

print("== the hub says so once ==")
local said = {}
local hub = { FCPopup = { getResponse = function(_, msg, btn, cb) said[#said + 1] = msg end } }
for _ = 1, 50 do PRO.step(hub) end
ck(#said == 1 and said[1]:find("Restart the game once", 1, true), "the restart notice: " .. tostring(said[1]))
ck(st.restart == nil, "and it is not due any more")
for _ = 1, 1300 do PRO.step(hub) end
ck(#said == 1, "never twice")

print("== a changed look is written again; the errors are told ==")
st.look.hair = L.hairs[41]
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(count("pro:db:") == 2 and lastSent("pro:db:"):find("hairtypecode=" .. L.hairs[41] .. ",", 1, true) and st.restart == true, "a new hairstyle: written, restart due")
ck(count("pro:get:") == 1, "the body's own values are read only the first time")
st.look.hair = L.hairs[42]; st.restart = nil
libpv.dbErr = "players table CRC mismatch"
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(st.dbErr == "players table CRC mismatch" and not st.restart, "a refused write: " .. tostring(st.dbErr))
PRO.G.noticed = nil; said = {}
for _ = 1, 50 do PRO.step(hub) end
ck(#said == 1 and said[1]:find("could not be saved", 1, true) and said[1]:find("CRC mismatch", 1, true), "the error notice: " .. tostring(said[1]))
libpv.dbErr = nil
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(st.dbErr == nil and st.restart == true, "the next bind writes it")
st.look.hair = L.hairs[43]
libpv.caps = ""
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(st.dbErr and st.dbErr:find("older build", 1, true), "an older libpv: " .. tostring(st.dbErr))
libpv.caps = "pro:1"
PRO.bind(SV, { SquadMgtService = {} }, nil)
-- a database that keeps surnames (the body's row had one): his goes in too
local keepOrig = st.orig
st.orig = "height=181;Body|Guy|B. Guy|Guy"; st.look.hair = L.hairs[44]
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(lastSent("pro:name:") == "pro:name:" .. BODY .. ":Davun|Oluwa|D. Oluwa|Oluwa", "a database with surnames gets his: " .. tostring(lastSent("pro:name:")))
st.orig = keepOrig; st.look.hair = L.hairs[43]
PRO.bind(SV, { SquadMgtService = {} }, nil)
st.restart, st.dbErr = nil, nil

print("== the AI manager's team sheet ==")
local FCPopupStub = { new = function() return {} end }
local PlayerCareer = assert(loadfile(D .. "PlayerCareer.lua"))(SV, FCPopupStub)
local pc = PlayerCareer:new({ services = {} })
rawset(_G, "g_PlayerCareer", pc)
math.randomseed(7)
local started = 0
for d = 1, 60 do
  GLOBAL_DATE_PLACEHOLDER = string.format("%02d/08/25", (d % 28) + 1) .. d
  local xi = pc:pickAISquad(USER, 20)
  ck(xi and #xi == 11, "eleven named")
  local all = data.TeamCachedData[USER].players
  ck(#all == 23, "the squad keeps all 23 (" .. #all .. ")")
  for _, id in ipairs(xi or {}) do if id == BODY then started = started + 1 end end
end
GLOBAL_DATE_PLACEHOLDER = "01/09/25"
print("    started " .. started .. "/60")
ck(started > 0 and started < 60, "a 60 OVR newcomer at a 75 club starts sometimes: " .. started .. "/60")

print("== a save and a load ==")
local saved = { pro = PRO.serialize(), mode = "player", playerCareerID = data.PlayerCareerPlayerID, youth = Y.serialize(), playerDev = CD.serialize() }
ck(saved.pro and saved.pro.id == BODY and saved.youth and saved.playerDev, "saved")
local keep = data
data = { InPlayerCareerMode = true }
SV.get = function(k) return data[k] end; SV.set = function(k, v) data[k] = v end
PRO.restore(SV, saved.pro)
ck(data.PlayerCareerPlayerID == BODY and data._prismPro.kind == "new" and not data._prismPro.pending, "restored")
ck(data._prismPro.sur == "Oluwa" and data._prismPro.look.hair == L.hairs[43] and type(data._prismPro.last) == "table", "with his names and look")
local st2 = Y.decode(saved.youth)
ck(st2 and st2.reg[BODY] and st2.reg[BODY].club == USER and st2.reg[BODY].nm == "Davun Oluwa", "the youth registry keeps him at the club")
data = keep
SV.get = function(k) return data[k] end; SV.set = function(k, v) data[k] = v end

print("== the season end never retires him ==")
local judged = 0
rawset(_G, "F16_SVC", { Cmd = function() end, Out = function() return "" end })   -- the birthdate reads
local origRetire = Y.retireChance
Y.retireChance = function() judged = judged + 1; return 1 end   -- everyone the roll sees retires
PRO.id = PRO.id
local okS, errS = pcall(Y.seasonEnd)
Y.retireChance = origRetire
ck(okS, "the season end ran: " .. tostring(errS))
ck(judged >= 20, "the roll judged the rest of the squad (" .. judged .. ")")
local gone = 0
for id = 1, 22 do if not getCachedTeamPlayers(USER) then break end end
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID ~= BODY then gone = gone + 1 end end
ck(Y.get(BODY) ~= nil and Y.get(BODY).k == "C", "still a player after a season end where everyone else retired")

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
