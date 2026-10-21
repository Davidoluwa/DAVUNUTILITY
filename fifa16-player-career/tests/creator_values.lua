-- Prints every look Create Your Player can send (each row value on top of the defaults) as "<key>=<value> <pro:db fields>",
-- for libpv/tests-f16service/test_pro_values.c, which runs them through the real database writer.
-- usage: lua5.1 tests/creator_values.lua <ux dir> | test_pro_values <fifa_ng_db.db> <body id>
local UX = arg[1]
local D = UX .. "/flows/mainflow/gamemodes/Liga/Data/"
rawset(_G, "CAREER_SESSION_VARS", { get = function() end, set = function() end })
GLOBAL_DATE_PLACEHOLDER = "01/07/25"
rawset(_G, "PlayerDev", dofile(D .. "PlayerDev.lua"))
dofile(D .. "PrismProLook.lua")
local PRO = dofile(D .. "PrismPro.lua")
rawset(_G, "PrismSetup", { native = function() return true end })
local specs = {}
local popup = { showScreen = function(_, m, sp) specs[#specs + 1] = sp end }
local ctx = { body = { id = 1, club = 2 }, club = 3, clubName = "X", names = { first = "A", last = "B" } }
PRO.openPage(popup, 1, ctx); PRO.openPage(popup, 2, ctx)
-- every value of every row, each on top of the defaults, as the database fields PRO would send
local d1, d2 = PRO.pageDefaults(1), PRO.pageDefaults(2)
local n = 0
for page, sp in ipairs(specs) do
  for key, def in pairs(sp.def) do
    for _, v in ipairs(def[3]) do
      local c1, c2 = {}, {}
      for k, x in pairs(d1) do c1[k] = x end
      for k, x in pairs(d2) do c2[k] = x end
      if page == 1 then c1[key] = v[2] else c2[key] = v[2] end
      local st = { pos = c1.pos, foot = c1.foot, height = c1.height, weight = c1.weight,
        look = { head = c2.head, tone = c2.tone, skinType = c2.skinType, eyes = c2.eyes, brow = c2.brow, side = c2.side,
                 beard = c2.beard, beardColour = c2.beardColour, hair = c2.hair, hairColour = c2.hairColour, boots = c2.boots } }
      print(key .. "=" .. tostring(v[2]) .. " " .. PRO.fieldList(PRO.lookFields(st)))
      n = n + 1
    end
  end
end
io.stderr:write(n .. " values\n")
