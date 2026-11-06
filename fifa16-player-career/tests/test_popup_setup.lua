-- Host test for the Popup skin's "setup" mode on Lua 5.1: Create Your Player's two pages (PrismPro.openPage) and the
-- stock Career Setup on the same model, driven through its action handlers the way native taps drive it.
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
dofile(D .. "PrismProLook.lua")
dofile(D .. "PrismSetup.lua")
local spec = dofile(UX .. "/flows/prism/skins/Popup/Popup.skin.lua")
ck(type(spec) == "table" and type(spec.model) == "function", "the skin loads")
for _, b in ipairs({ "bnd_cs_hdr", "bnd_cs_go", "bnd_cs_rst", "bnd_cs_pro", "bnd_cs_std", "bnd_cs_body", "bnd_cs_face" }) do
  ck(spec.pass[b] == b, b .. " is passed to the scene")
end

local function session()
  local env = {}
  local s = { handlers = {}, env = env }
  function s:onPublish(b, v) env[b] = v end
  return s, env
end
-- libpv: the commands, and the preview override's replies
local sent = {}
rawset(_G, "F16_SVC", { Cmd = function(c) sent[#sent + 1] = c end, Out = function() return "ok:1" end })
local function lastOf(prefix) for i = #sent, 1, -1 do if sent[i]:sub(1, #prefix) == prefix then return sent[i], i end end end
rawset(_G, "PrismSetup", setmetatable({ native = function() return true end }, { __index = rawget(_G, "PrismSetup") }))
local popup = { showScreen = function(self, mode, sp, cb) self.mode, self.spec, self.cb = mode, sp, cb end }
local ctx = { body = { id = 4242, club = 753 }, club = 10, clubName = "Flamengo", names = { first = "Davun", last = "Oluwa" } }
local function open(page)
  local done
  PRO.openPage(popup, page, ctx, function(ok) done = ok end)
  local s, env = session()
  local answered
  local o = { data = { setup = popup.spec }, _clickEvent = function(_, n) answered = n; popup.cb(n) end }
  ck(spec.model(s, o) == true, "page " .. page .. " runs")
  return s.handlers, env, function() return done, answered end
end

print("== page 1: the player ==")
local H, env, res = open(1)
ck(env.bnd_cs_hdr == "Create Your Player" and env.bnd_cs_go == "Next: Face" and env.bnd_cs_rst == "Reset", "header and buttons")
ck(env.bnd_cs_pro == true and env.bnd_cs_std == false and env.bnd_cs_body == true and env.bnd_cs_face == false, "the whole player in the 3D place")
ck(env.bnd_cs_tn1 == "Player" and env.bnd_cs_tn2 == "Ability" and env.bnd_cs_tn3 == "Attack" and env.bnd_cs_tn4 == "Defence", "tabs")
ck(env.bnd_cs_l1 == "Position" and env.bnd_cs_v1 == "Striker (ST)" and env.bnd_cs_l3 == "Preferred Foot" and env.bnd_cs_v3 == "Right", "player rows")
local d = tostring(env.bnd_cs_desc)
ck(d:find("Davun Oluwa", 1, true) and d:find("ST  ·  60 OVR  ·  85 POT  ·  Age 17", 1, true) and d:find("180 cm  ·  75 kg  ·  Right", 1, true), "description: " .. d)
local look, iLook = lastOf("pro:look:4242:")
local show, iShow = lastOf("pc3d:slot:4:show:4242:10:")
local _, iRe = lastOf("pc3d:slot:4:reinit")
ck(look and look:find("hashighqualityhead=0", 1, true) and look:find("headclasscode=1", 1, true), "the preview override for the body: " .. tostring(look))
ck(show and iLook < iShow and iShow < iRe, "override, then show, then rebuild")
H.act_cs_tab2()
ck(env.bnd_cs_l3 == "Height" and env.bnd_cs_v3 == "180 cm" and env.bnd_cs_l4 == "Weight" and env.bnd_cs_v4 == "75 kg", "ability rows")
H.act_cs_row3(); H.act_cs_next(); H.act_cs_next()
ck(env.bnd_cs_v3 == "182 cm" and tostring(env.bnd_cs_desc):find("182 cm", 1, true), "height steps by one centimetre")
H.act_cs_tab1(); H.act_cs_row1(); H.act_cs_prev()
ck(env.bnd_cs_v1 == "Goalkeeper (GK)" and lastOf("pc3d:slot:4:show:"):match(":2$"), "a keeper is shown in the keeper kit")
H.act_cs_next()
H.act_cs_row3(); H.act_cs_next()
ck(env.bnd_cs_v3 == "Left", "left foot")
H.act_cs_start()
local ok, ans = res()
ck(ans == 100 and ok == true, "Next answers 100")
ck(ctx.c1.height == 182 and ctx.c1.foot == 2 and ctx.c1.pos == 25, "the page's choices are kept")

print("== page 2: the face ==")
sent = {}
H, env, res = open(2)
ck(env.bnd_cs_hdr == "Create Your Face" and env.bnd_cs_go == "Start Career", "header and button")
ck(env.bnd_cs_body == false and env.bnd_cs_face == true, "head and shoulders in the 3D place")
ck(env.bnd_cs_tn1 == "Head" and env.bnd_cs_tn2 == "Face" and env.bnd_cs_tn3 == "Hair" and env.bnd_cs_tn4 == "Boots", "tabs")
ck(env.bnd_cs_l1 == "Head Shape" and env.bnd_cs_v1:match("^%d+ / 186$") and env.bnd_cs_l2 == "Skin Tone" and env.bnd_cs_v2:match(" / 7$"), "head rows: " .. tostring(env.bnd_cs_v1))
local function look_has(k) local l = lastOf("pro:look:4242:"); return l and l:find(k, 1, true) end
H.act_cs_row1(); H.act_cs_next()
local L = rawget(_G, "PRISM_PRO_LOOK")
local function at(list, v) for i, x in ipairs(list) do if x == v then return i end end end
local h0 = at(L.heads, PRO.pageDefaults(2).head)
ck(h0 and look_has("headtypecode=" .. L.heads[h0 % #L.heads + 1] .. ",") and lastOf("pc3d:slot:4:reinit"), "the next head is previewed: " .. tostring(lastOf("pro:look:")))
H.act_cs_tab2(); H.act_cs_row3()
ck(env.bnd_cs_l3 == "Facial Hair" and env.bnd_cs_v3 == "Clean Shaven", "facial hair starts clean shaven")
H.act_cs_next()
ck(env.bnd_cs_v3 == "Style 1" and look_has("facialhairtypecode=1"), "a beard")
H.act_cs_row1(); H.act_cs_next(); H.act_cs_next()
ck(look_has("eyebrowcode=0") or look_has("eyebrowcode=2"), "eyebrows step")
H.act_cs_tab3(); H.act_cs_row2()
ck(env.bnd_cs_l2 == "Hair Colour" and env.bnd_cs_v2 == "Black", "hair colour: " .. tostring(env.bnd_cs_v2))
H.act_cs_next()
ck(env.bnd_cs_v2 == "Dark Brown" and look_has("haircolorcode=3"), "dark brown is code 3")
H.act_cs_row1()
local hi = at(L.hairs, PRO.pageDefaults(2).hair)
ck(env.bnd_cs_v1 == hi .. " / " .. #L.hairs, "the default hairstyle's place: " .. tostring(env.bnd_cs_v1))
for _ = 1, hi do H.act_cs_prev() end
ck(env.bnd_cs_v1 == #L.hairs .. " / " .. #L.hairs and look_has("hairtypecode=" .. L.hairs[#L.hairs] .. ","), "hairstyles wrap round")
H.act_cs_tab4()
ck(env.bnd_cs_n == 1 and env.bnd_cs_l1 == "Boots" and env.bnd_cs_v1:match(" / 172$"), "boots")
local d2 = tostring(env.bnd_cs_desc)
ck(d2:find("Davun Oluwa", 1, true) and d2:find("182 cm", 1, true), "the face page knows the player page")
H.act_cs_back()
ok, ans = res()
ck(ans == 0 and ok == false, "Back answers 0")

print("== the stock Career Setup is unchanged ==")
local s, env3 = session()
local stockAnswer
local o = { data = { setup = { choices = { grow = 150 } } }, _clickEvent = function(_, n) stockAnswer = n end }
spec.model(s, o)
ck(env3.bnd_cs_hdr == "Career Setup" and env3.bnd_cs_go == "Start Career" and env3.bnd_cs_rst == "Restore Defaults", "stock header and buttons")
ck(env3.bnd_cs_pro == false and env3.bnd_cs_std == true and env3.bnd_cs_body == false and env3.bnd_cs_face == false, "stock info panel, no 3D place")
ck(env3.bnd_cs_tn1 == "Competitions" and env3.bnd_cs_tn4 == "Saving", "stock tabs")
s.handlers.act_cs_tab2()
ck(env3.bnd_cs_l1 == "Player Growth" and env3.bnd_cs_v1 == "Fast", "stock rows keep their choices")
s.handlers.act_cs_start()
ck(stockAnswer == 100 and o.data.setup.result and o.data.setup.result.grow == 150 and o.data.setup.result.pos == nil, "stock result has only its own settings")

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
