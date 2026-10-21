-- Host test for a created player's whole way in, on Lua 5.1 with the real PlayerDev, CareerDev, PrismYouth, PlayerCareer
-- and PrismPro (the engine's reads are faked): the boot's choice and Create Your Player, the hub applying the build,
-- the squad row, the match override table, the AI manager's team sheet, a save and a load.
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
dofile(D .. "PrismProFaces.lua")
local PRO = dofile(D .. "PrismPro.lua")
local body = PRO.faceAt(2, 1, 1)
data.TeamCachedData[ORG] = { players = { row(body.id, "CM", 58, "Body Guy") }, league = 99 }
data.TeamCachedData[body.club] = data.TeamCachedData[body.club] or { players = { row(body.id, "CM", 58, "Body Guy") }, league = 99 }
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

print("== TeamSelect's last step: the choice, then Create Your Player ==")
local events, popups = {}, {}
local nav = { Event = function(_, e, d) events[#events + 1] = e .. ((d and d.vvm) and (" " .. d.vvm) or "") end }
local FCP = {}
FCP.__index = FCP
function FCP.new(cls, init) return setmetatable({ nav = init.nav }, cls) end
function FCP:getResponse(msg, btn, cb) popups[#popups + 1] = { msg = msg, btn = btn, cb = cb } end
function FCP:showScreen(mode, spec, cb) popups[#popups + 1] = { mode = mode, spec = spec, cb = cb } end
rawset(_G, "PRISM_FCPOPUP", FCP)
rawset(_G, "PrismSetup", setmetatable({ native = function() return true end }, { __index = rawget(_G, "PrismSetup") }))
local ts = { nav = nav, api = function(n) return { GetCurrentPlayerLineup = function(_, club) local e = data.TeamCachedData[club]; return e and e.players or {} end } end,
  loc = { LocalizeString = function(k) return "Club " .. k:match("(%d+)$") end } }
ck(PRO.start(ts, SV) == true, "PrismPro takes the step")
ck(popups[1] and popups[1].btn[1] == "Create Your Player" and popups[1].btn[2] == "Play as a Squad Player", "asks which way")
popups[1].cb(1)
ck(popups[2] and popups[2].mode == "setup" and popups[2].spec.title == "Create Your Player" and popups[2].spec.club == "Club 10", "Create Your Player opens")
-- Back from the creator asks again; then the second way: a squad player
popups[2].cb(0)
ck(popups[3] and popups[3].btn and popups[3].btn[1] == "Create Your Player", "Back asks again")
popups[3].cb(1)
local choices = {}
for k, v in pairs(PRO.CREATOR_DEFAULTS) do choices[k] = v end
choices.pos, choices.age, choices.ovr, choices.pot, choices.sho, choices.pac = 25, 17, 60, 88, 2, 1
popups[4].spec.result = choices
popups[4].cb(100)
local st = data._prismPro
ck(st and st.pending and st.id == body.id and st.kind == "new" and st.pos == 25 and st.pot == 88, "the build waits for the hub")
ck(data.PlayerCareerPlayerID == body.id, "PlayerCareerPlayerID is the body")
ck(events[#events - 1] == "evt_team_select" and events[#events] == "evt_hide_overlay", "the boot goes on to the hub")
ck(st.js and st.js ~= nil and st.js >= 1 and st.js <= 99, "a jersey number: " .. tostring(st.js))
local age = PD.ageOf and (PD.dayOfCareer("01/07/25") - st.b) / 365.2425
ck(age and age > 16.5 and age < 18, "born 17 years ago: " .. tostring(age))

print("== the hub binds: the body joins the club with the build ==")
PRO.bind(SV, { SquadMgtService = {} }, nil)
ck(st.pending == nil, "applied")
local y = Y.get(body.id)
ck(y and y.k == "C" and y.club == USER and y.nm == "Body Guy" and y.p == 25 and y.t == 88, "a youth of the user's club: " .. tostring(y and y.club))
local mine
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID == body.id then mine = r end end
ck(mine and mine.position == "ST" and mine.playerName == "Body Guy" and mine.rating == 60, "his squad row: " .. tostring(mine and mine.position) .. " " .. tostring(mine and mine.rating))
local inOrg = false
for _, r in ipairs(data.TeamCachedData[body.club].players) do if r.CARD_ID == body.id then inOrg = true end end
ck(not inOrg, "he left his database club")
local p = PD.get(body.id)
ck(p and p.ovr == 60 and p.pos == 25 and p.pot == 88 and PD.formulaArr(p.a, 25, 1) == 60, "PlayerDev has the build")
ck(p and p.b and p.b[1] == 55, "the base is his host's database values (what the engine reads)")
local ov = CD.matchOverrides({ USER })
local n = 0
for _, e in ipairs(ov) do if e[1] == body.id then n = n + 1 end end
ck(n >= 25, "real matches get his build through the override table (" .. n .. " values)")
PRO.bind(SV, { SquadMgtService = {} }, nil)
local count = 0
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID == body.id then count = count + 1 end end
ck(count == 1, "binding again changes nothing")

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
  for _, id in ipairs(xi or {}) do if id == body.id then started = started + 1 end end
end
GLOBAL_DATE_PLACEHOLDER = "01/09/25"
print("    started " .. started .. "/60")
ck(started > 0 and started < 60, "a 60 OVR newcomer at a 75 club starts sometimes: " .. started .. "/60")

print("== a save and a load ==")
local saved = { pro = PRO.serialize(), mode = "player", playerCareerID = data.PlayerCareerPlayerID, youth = Y.serialize(), playerDev = CD.serialize() }
ck(saved.pro and saved.pro.id == body.id and saved.youth and saved.playerDev, "saved")
local keep = data
data = { InPlayerCareerMode = true }
SV.get = function(k) return data[k] end; SV.set = function(k, v) data[k] = v end
PRO.restore(SV, saved.pro)
ck(data.PlayerCareerPlayerID == body.id and data._prismPro.kind == "new" and not data._prismPro.pending, "restored")
local st2 = Y.decode(saved.youth)
ck(st2 and st2.reg[body.id] and st2.reg[body.id].club == USER and st2.reg[body.id].nm == "Body Guy", "the youth registry keeps him at the club")
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
for _, r in ipairs(data.TeamCachedData[USER].players) do if r.CARD_ID ~= body.id then gone = gone + 1 end end
ck(Y.get(body.id) ~= nil and Y.get(body.id).k == "C", "still a player after a season end where everyone else retired")

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
