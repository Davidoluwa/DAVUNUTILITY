-- Host test for the Popup skin's "setup" mode on Lua 5.1: Create Your Player (PrismPro's spec) and the stock Career
-- Setup on the same model, driven through its action handlers the way native taps drive it.
-- usage: lua5.1 tests/test_popup_setup.lua <ux dir>
local UX = arg[1] or "ux"
local D = UX .. "/flows/mainflow/gamemodes/Liga/Data/"
local pass, fail = 0, 0
local function ck(c, what) if c then pass = pass + 1 else fail = fail + 1; print("  FAIL  " .. what) end end

local data = {}
rawset(_G, "CAREER_SESSION_VARS", { get = function(k) return data[k] end, set = function(k, v) data[k] = v end })
GLOBAL_DATE_PLACEHOLDER = "01/07/25"
local PD = dofile(D .. "PlayerDev.lua"); rawset(_G, "PlayerDev", PD)
local PRO = dofile(D .. "PrismPro.lua")
dofile(D .. "PrismProFaces.lua")
dofile(D .. "PrismSetup.lua")
local spec = dofile(UX .. "/flows/prism/skins/Popup/Popup.skin.lua")
ck(type(spec) == "table" and type(spec.model) == "function", "the skin loads")
for _, b in ipairs({ "bnd_cs_hdr", "bnd_cs_go", "bnd_cs_rst", "bnd_cs_pro", "bnd_cs_std" }) do ck(spec.pass[b] == b, b .. " is passed to the scene") end

local function session()
  local env = {}
  local s = { handlers = {}, env = env }
  function s:onPublish(b, v) env[b] = v end
  return s, env
end

print("== Create Your Player ==")
-- what PRO.open hands to FCPopup:showScreen("setup", ...), with the 3D preview commands recorded
local shown = {}
rawset(_G, "F16_SVC", { Cmd = function(c) shown[#shown + 1] = c end, Out = function() return "" end })
rawset(_G, "PrismSetup", setmetatable({ native = function() return true end }, { __index = rawget(_G, "PrismSetup") }))
local answered, built
local popup = { showScreen = function(self, mode, sp, cb) self.mode, self.spec, self.cb = mode, sp, cb end }
PRO.open(popup, nil, 10, "Flamengo", function(b) built = b end)
ck(popup.mode == "setup", "opens the setup mode")
local s, env = session()
local o = { data = { setup = popup.spec }, _clickEvent = function(_, n) answered = n; popup.cb(n) end }
ck(spec.model(s, o) == true, "the model runs")
ck(env.bnd_cs_on == true, "the setup screen is on")
ck(env.bnd_cs_hdr == "Create Your Player" and env.bnd_cs_go == "Start Career" and env.bnd_cs_rst == "Reset", "header and buttons")
ck(env.bnd_cs_pro == true and env.bnd_cs_std == false, "the creator's info panel and 3D place")
ck(env.bnd_cs_tn1 == "Player" and env.bnd_cs_tn2 == "Attack" and env.bnd_cs_tn3 == "Defence" and env.bnd_cs_tn4 == "Look", "tabs")
ck(env.bnd_cs_l1 == "Position" and env.bnd_cs_v1 == "Striker (ST)" and env.bnd_cs_v2 == "17" and env.bnd_cs_v3 == "60 OVR", "player rows: " .. tostring(env.bnd_cs_v1))
ck(env.bnd_cs_club == "Flamengo", "club line")
ck(tostring(env.bnd_cs_desc):find("ST  ·  60 OVR  ·  85 POT  ·  Age 17", 1, true) ~= nil, "description: " .. tostring(env.bnd_cs_desc))
ck(#shown >= 1 and shown[#shown]:match("^pc3d:slot:4:show:%d+:10:0$") ~= nil, "the 3D model shows on open: " .. tostring(shown[#shown]))
local H = s.handlers
-- the Look tab: the next face shows a different body in slot 4
H.act_cs_tab4()
ck(env.bnd_cs_n == 3 and env.bnd_cs_l2 == "Face" and env.bnd_cs_v2 == "1", "look tab")
local before = shown[#shown]
H.act_cs_row2(); H.act_cs_next()
ck(env.bnd_cs_v2 == "2" and shown[#shown] ~= before and shown[#shown]:match("^pc3d:slot:4:show:") ~= nil, "next face, new model: " .. tostring(shown[#shown]))
H.act_cs_row1(); H.act_cs_prev(); H.act_cs_prev()
ck(env.bnd_cs_v1 == "Dark", "skin tone wraps backwards to the last tone: " .. tostring(env.bnd_cs_v1))
-- the Attack tab: pace up
H.act_cs_tab2(); H.act_cs_row1(); H.act_cs_next(); H.act_cs_next()
ck(env.bnd_cs_v1 == "Elite", "pace focus Elite")
-- position GK: the 3D model wears the keeper kit
H.act_cs_tab1(); H.act_cs_row1(); H.act_cs_prev()
ck(env.bnd_cs_v1 == "Goalkeeper (GK)" and shown[#shown]:match(":2$") ~= nil, "a keeper is shown in the keeper kit")
H.act_cs_next()
H.act_cs_start()
ck(answered == 100, "Start Career answers 100")
ck(built and built.pos == 25 and built.focus.pac == 2 and built.body and built.body.id and built.ovr == 60 and built.pot == 85, "the build comes back")
local p3 = {}
for _, c in ipairs(shown) do if c:sub(1, 5) == "pc3d:" then p3[#p3 + 1] = c end end
ck(p3[#p3 - 1] == "pc3d:slot:4:hide" and p3[#p3] == "pc3d:slot:4:cleanup", "the 3D model is hidden and cleaned up on close")
local a = built and PRO.attrs(built.pos, built.ovr, built.focus, built.seed)
ck(a and PD.formulaArr(a, 25, 1) == 60, "the build's attributes give 60")

print("== Back answers 0 and builds nothing ==")
built, answered = "untouched", nil
PRO.open(popup, nil, 10, "", function(b) built = b end)
s, env = session(); o = { data = { setup = popup.spec }, _clickEvent = function(_, n) answered = n; popup.cb(n) end }
spec.model(s, o); s.handlers.act_cs_back()
ck(answered == 0 and built == nil, "back")

print("== the stock Career Setup is unchanged ==")
s, env = session()
local stockAnswer
o = { data = { setup = { choices = { grow = 150 } } }, _clickEvent = function(_, n) stockAnswer = n end }
spec.model(s, o)
ck(env.bnd_cs_hdr == "Career Setup" and env.bnd_cs_go == "Start Career" and env.bnd_cs_rst == "Restore Defaults", "stock header and buttons")
ck(env.bnd_cs_pro == false and env.bnd_cs_std == true, "stock info panel, no 3D place")
ck(env.bnd_cs_tn1 == "Competitions" and env.bnd_cs_tn4 == "Saving", "stock tabs")
s.handlers.act_cs_tab2()
ck(env.bnd_cs_l1 == "Player Growth" and env.bnd_cs_v1 == "Fast", "stock rows keep their choices")
s.handlers.act_cs_start()
ck(stockAnswer == 100 and o.data.setup.result and o.data.setup.result.grow == 150 and o.data.setup.result.pos == nil, "stock result has only its own settings")

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
