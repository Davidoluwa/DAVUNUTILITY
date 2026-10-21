-- ProName - Player Career's name entry: the career keyboard (its layout and its Prism skin, Keyboard.skin.lua) on a VM of
-- its own, so nothing of the league keyboard's globals is touched.
-- PrismPro.askName opens it as an overlay with data = { nav, title, crumb, text, max, done = function(name) }:
-- Enter answers the typed name (each word starts with a capital, single spaces, at most `max` characters, default 20);
-- Enter on an empty name answers nil (the user goes back). The overlay closes before done runs.
local ProName = {}
local LETTERS = "qwertyuiopasdfghjklzxcvbnm"

function ProName:new(init)
  local o = init or {}
  setmetatable(o, self)
  self.__index = self
  local d = type(o.data) == "table" and o.data or {}
  o.nav = d.nav or o.nav
  o.done = d.done
  o.text = tostring(d.text or "")
  o.max = tonumber(d.max) or 20
  o.title = tostring(d.title or "Player Name")
  o.crumb = tostring(d.crumb or "Create Your Player")
  o.im.Subscribe("bnd_matchday_label", function() o:publish() end)
  o.im.Subscribe("bnd_kb_title", function() o.im.Publish("bnd_kb_title", o.title) end)
  o.im.Subscribe("bnd_kb_crumb", function() o.im.Publish("bnd_kb_crumb", o.crumb) end)
  for i = 1, #LETTERS do
    local c = LETTERS:sub(i, i)
    o.im.RegisterAction("act_" .. c, function() o:type(c) end)
  end
  o.im.RegisterAction("act_dot", function() o:type(" ") end)   -- the keyboard's space key
  o.im.RegisterAction("act_backspace", function() o.text = o.text:sub(1, -2); o:publish() end)
  o.im.RegisterAction("act_delete", function() o.text = ""; o:publish() end)
  o.im.RegisterAction("act_submit", function() o:finish() end)
  o:publish()
  return o
end

function ProName:publish()
  self.im.Publish("bnd_matchday_label", self.text)
end

--- One key: a letter (a capital at the start of a word) or a space (never leading, never doubled).
function ProName:type(c)
  if #self.text >= self.max then return end
  if c == " " then
    if self.text == "" or self.text:sub(-1) == " " then return end
  elseif self.text == "" or self.text:sub(-1) == " " then
    c = c:upper()
  end
  self.text = self.text .. c
  self:publish()
end

--- Enter: the overlay closes and done gets the name (nil for an empty one).
function ProName:finish()
  if self.answered then return end
  self.answered = true
  local name = self.text:gsub("^%s+", ""):gsub("%s+$", "")
  if self.nav then self.nav.Event(nil, "evt_hide_overlay") end
  if type(self.done) == "function" then self.done(name ~= "" and name or nil) end
end

function ProName:update(elapsedTime)
end

function ProName:finalize()
  for i = 1, #LETTERS do self.im.UnregisterAction("act_" .. LETTERS:sub(i, i)) end
  for _, a in ipairs({ "act_dot", "act_backspace", "act_delete", "act_submit" }) do self.im.UnregisterAction(a) end
  for _, b in ipairs({ "bnd_matchday_label", "bnd_kb_title", "bnd_kb_crumb" }) do self.im.Unsubscribe(b) end
end

return (select(select('#', ...) - 2, ...)).wrap(ProName, (select(select('#', ...), ...)), (select(select('#', ...) - 1, ...))) -- Prism skin (PrismSkin.wrap(Class, spec, theme))
