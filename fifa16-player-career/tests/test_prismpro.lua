-- Host test for PrismPro (Player Career) on Lua 5.1, with the real PlayerDev, PrismYouth and PrismI18n.
-- usage: lua5.1 tests/test_prismpro.lua <ux dir>
local UX = arg[1] or "ux"
local D = UX .. "/flows/mainflow/gamemodes/Liga/Data/"
local pass, fail = 0, 0
local function ck(c, what) if c then pass = pass + 1 else fail = fail + 1; print("  FAIL  " .. what) end end

-- the career's sessionVars (one context)
local data = {}
local SV = { get = function(k) return data[k] end, set = function(k, v) data[k] = v end }
rawset(_G, "CAREER_SESSION_VARS", SV)
GLOBAL_DATE_PLACEHOLDER = "15/08/25"
CAREER_FULL_YEAR = 2025
currentSelectedTeamID = 10

local PD = dofile(D .. "PlayerDev.lua"); rawset(_G, "PlayerDev", PD)
local PRO = dofile(D .. "PrismPro.lua")
dofile(D .. "PrismProFaces.lua")

print("== attributes: the overall formula gives exactly the chosen level, focus moves points ==")
for _, pos in ipairs({ 25, 14, 5, 0, 27, 10, 3 }) do
  for _, ovr in ipairs({ 45, 60, 75, 80 }) do
    local a = PRO.attrs(pos, ovr, { pac = 2, sho = -1 }, 1234)
    ck(a and #a == #PD.ATTRS, "33 attributes pos " .. pos)
    ck(a and PD.formulaArr(a, pos, 1) == ovr, string.format("pos %d ovr %d -> formula %s", pos, ovr, a and PD.formulaArr(a, pos, 1)))
    local lo, hi = 99, 0
    for _, v in ipairs(a or {}) do lo = math.min(lo, v); hi = math.max(hi, v) end
    ck(lo >= 5 and hi <= 99, "range 5..99")
  end
end
local function face(a, k) for _, f in ipairs(PRO.faces(a, false)) do if f[1] == k then return f[2] end end end
local fast = PRO.attrs(25, 65, { pac = 2 }, 7)
local slow = PRO.attrs(25, 65, { pac = -2 }, 7)
ck(face(fast, "PAC") - face(slow, "PAC") >= 20, "pace focus: +2 vs -2 differ by >= 20 PAC (" .. face(fast, "PAC") .. " vs " .. face(slow, "PAC") .. ")")
ck(PD.formulaArr(fast, 25, 1) == 65 and PD.formulaArr(slow, 25, 1) == 65, "both still 65 OVR")
local d1 = PRO.attrs(14, 70, {}, 99); local d2 = PRO.attrs(14, 70, {}, 99)
ck(table.concat(d1, ",") == table.concat(d2, ","), "deterministic for a seed")
local gk = PRO.attrs(0, 70, {}, 5)
local ix = {}; for i, n in ipairs(PD.ATTRS) do ix[n] = i end
ck(gk[ix.gkDiving] > gk[ix.finishing] + 15, "a keeper's keeping beats his finishing")

print("== faces ==")
local T = rawget(_G, "PRISM_PRO_FACES")
ck(T and T.n == 19407 and #T.labels == 7, "19407 faces in 7 tones")
local b1 = PRO.faceAt(1, 1, 1); local b2 = PRO.faceAt(1, 1, 2); local bw = PRO.faceAt(7, 99, 40)
ck(b1 and b2 and b1.id ~= b2.id and b1.club, "faces step")
ck(bw and bw.id, "a set past the end of a small tone wraps round")

print("== the team sheet: trust decides, within his line; nobody leaves the squad ==")
data.InPlayerCareerMode = true
data._prismPro = { id = 900, trust = 50, car = {}, sea = {}, hist = {}, last = {} }
local function row(id, pos, r) return { CARD_ID = id, position = pos, rating = r } end
local function squad()
  local xi = { row(1, "GK", 80), row(2, "CB", 75), row(3, "CB", 74), row(4, "LB", 72), row(5, "RB", 72), row(6, "CM", 76),
               row(7, "CM", 75), row(8, "CDM", 74), row(9, "LW", 78), row(10, "RW", 77), row(11, "ST", 79) }
  local bench = { row(12, "GK", 70), row(13, "CB", 69), row(14, "CM", 70), row(15, "ST", 71), row(16, "LB", 66), row(17, "RW", 68), row(18, "CDM", 67) }
  local me = row(900, "ST", 64)
  local eligible = {}
  for _, p in ipairs(xi) do eligible[#eligible + 1] = p end
  for _, p in ipairs(bench) do eligible[#eligible + 1] = p end
  eligible[#eligible + 1] = me
  return xi, bench, eligible
end
local function count(list, id) local n = 0 for _, p in ipairs(list) do if p.CARD_ID == id then n = n + 1 end end return n end
local starts, n = 0, 0
for t = 0, 100, 10 do
  data._prismPro.trust = t
  local s = 0
  for k = 1, 400 do
    local xi, bench, el = squad()
    local r = (k * 7919 % 10007) / 10007
    PRO.adjustXI(xi, bench, el, "balanced", function() return r end)
    local inXI = count(xi, 900)
    s = s + inXI
    ck(#xi == 11, "XI has 11")
    ck(count(xi, 900) + count(bench, 900) <= 1, "the pro is in one place")
    -- every starter displaced is still in the squad (XI or bench)
    local seen = {}
    for _, p in ipairs(xi) do seen[p.CARD_ID] = true end
    for _, p in ipairs(bench) do seen[p.CARD_ID] = true end
    for id = 1, 18 do ck(seen[id] or id == 900, "player " .. id .. " still named") end
    if inXI == 1 then for i, p in ipairs(xi) do if p.CARD_ID == 900 then ck(p.position == "ST", "he starts as a forward") end end end
    local gks = 0; for _, p in ipairs(xi) do if p.position == "GK" then gks = gks + 1 end end
    ck(gks == 1, "one keeper")
  end
  if t == 0 then ck(s / 400 < 0.1, "trust 0: rarely starts (" .. s / 400 .. ")") end
  if t == 100 then ck(s / 400 > 0.6, "trust 100: usually starts (" .. s / 400 .. ")") end
  starts, n = starts + s, n + 400
end
data._prismPro.trust = 10
local rot = 0
for k = 1, 400 do
  local xi, bench, el = squad()
  PRO.adjustXI(xi, bench, el, "weak", function() return (k * 7919 % 10007) / 10007 end)
  rot = rot + count(xi, 900)
end
ck(rot / 400 > 0.8, "a rotation match is the fringe player's chance (" .. rot / 400 .. ")")

print("== match records, trust, season lines ==")
data._prismPro = { id = 900, kind = "new", pos = 25, trust = 45, car = { apps = 0, starts = 0, mins = 0, goals = 0, assists = 0, motm = 0, cs = 0, rs = 0, rn = 0 },
  sea = { apps = 0, starts = 0, mins = 0, goals = 0, assists = 0, motm = 0, cs = 0, rs = 0, rn = 0 }, season = 2025, hist = {}, last = {} }
PRO.onMatch(10, 20, 3, 1, { { id = 900, team = 10, mins = 90, goals = 2, assists = 1, rc = 0 } }, { [900] = 8.6 }, 900, false)
local st = data._prismPro
ck(st.car.apps == 1 and st.car.goals == 2 and st.car.assists == 1 and st.car.motm == 1 and st.car.starts == 1, "a played match is counted")
ck(st.trust > 55, "a man-of-the-match 8.6 lifts trust (" .. st.trust .. ")")
ck(st.last[1].res == "W 3-1" and st.last[1].r == 8.6, "last match line: " .. tostring(st.last[1].res))
PRO.onMatch(30, 10, 2, 0, { { id = 900, team = 10, mins = 20, on = 70, goals = 0, assists = 0, rc = 0 } }, { [900] = 5.5 }, nil, true)
ck(st.car.apps == 2 and st.car.starts == 1, "a sub appearance is not a start")
ck(st.last[1].res == "L 0-2", "an away defeat from his side")
PRO.onMatch(10, 40, 1, 1, { { id = 5, team = 10, mins = 90 } }, {}, nil, true)
ck(st.car.apps == 2 and #st.last == 3 and st.last[1].m == 0, "an unused match is listed with 0 minutes")
PRO.onMatch(50, 60, 1, 0, {}, {}, nil, true)
ck(#st.last == 3, "another club's match is ignored")
for i = 1, 20 do PRO.onMatch(10, 20, 1, 0, { { id = 900, team = 10, mins = 90, goals = 0 } }, { [900] = 6.5 }, nil, true) end
ck(#st.last == 10, "the last 10 matches are kept")
PRO.onSeasonEnd()
ck(#st.hist == 1 and st.hist[1].y == 2025 and st.hist[1].apps == 22 and st.sea.apps == 0 and st.season == 2026, "the season's line, and a new season")
local S = PRO.summary()
ck(S and S.car.apps == 22 and S.role ~= nil and S.avg ~= nil, "summary: " .. tostring(S and S.role) .. " avg " .. tostring(S and S.avg))

print("== save: serialize -> JSON-style keys -> restore ==")
local saved = PRO.serialize()
local function stringify(t) if type(t) ~= "table" then return t end local o = {} for k, v in pairs(t) do o[type(k) == "number" and tostring(k) or k] = stringify(v) end return o end
local function numkeys(t) if type(t) ~= "table" then return t end local o = {} for k, v in pairs(t) do o[tonumber(k) or k] = numkeys(v) end return o end
local back = numkeys(stringify(saved))
data._prismPro = nil; data.PlayerCareerPlayerID = nil
ck(PRO.restore(SV, back) == true, "restore")
ck(data.PlayerCareerPlayerID == 900 and data._prismPro.car.apps == 22 and #data._prismPro.hist == 1, "restored id and career")
ck(PRO.restore(SV, { nope = 1 }) == false, "a save without a pro is refused")
data.InPlayerCareerMode = false
ck(PRO.serialize() == nil and PRO.id() == nil, "outside a player career nothing is saved and there is no pro")

print("== pt-BR: the offer sentences and rows translate ==")
local okI = pcall(function() dofile(UX .. "/lua/prism/PrismI18nData.lua"); dofile(UX .. "/lua/prism/PrismI18n.lua") end)
local I = rawget(_G, "PRISM_I18N")
ck(okI and I and I.tr, "PrismI18n loads")
if I and I.tr then
  ck(I.tr("Create Your Player") == "Crie Seu Jogador", "title: " .. tostring(I.tr("Create Your Player")))
  local t1 = I.tr("Flamengo have made a £2.5M offer for you. Your role here: Key Player.")
  ck(t1 == "Flamengo fez uma proposta de £2.5M por você. Seu papel aqui: Jogador-Chave.", "offer: " .. tostring(t1))
  local t2 = I.tr("Santos want you on loan for 6 months. Your role here: Fringe Player.")
  ck(t2 == "Santos quer você emprestado por 6 meses. Seu papel aqui: Sem Espaço.", "loan: " .. tostring(t2))
  ck(I.tr("Set 12") == "Grupo 12" and I.tr("60 OVR") == "60 GER", "value templates: " .. tostring(I.tr("Set 12")) .. " / " .. tostring(I.tr("60 OVR")))
  ck(I.tr("Striker (ST)") == "Centroavante (ATA)", "positions")
end

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
