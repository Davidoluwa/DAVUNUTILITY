"""Applies the R98e PrismSkin.lua changes (match exit black screen) to every file given; each anchor must occur once."""
import sys

EDITS = [
# 1. real time
("""local clock = (os and os.clock) or function() return 0 end
""",
"""local clock = (os and os.clock) or function() return 0 end
-- Real time in whole seconds. libpv's timeouts are real time; os.clock is process cpu time (every thread), which runs at
-- its own pace while the engine works or waits.
local wall = (os and os.time) or function() return 0 end
"""),
# 2. the poll: libpv without any screen under live sessions
("""  if reason then
    log("native: back to the stock layouts: " .. reason)
    G.off = reason
    for _, s in pairs(G.sessions) do s:fallback(reason) end
    closeShellIfIdle()
    return
  end
""",
"""  if reason then
    log("native: back to the stock layouts: " .. reason)
    G.off = reason
    for _, s in pairs(G.sessions) do s:fallback(reason) end
    closeShellIfIdle()
    return
  end
  -- "s0": libpv has no layer open. Under live screens (open settled, not on their way out) that means it dropped them
  -- (see Session:goLive): three polls in a row, then they open again - the ones already shown at once, the others when
  -- their ready goes.
  local lost = false
  if any == "0" then for _, s in pairs(G.sessions) do if not s.dead and not s.leaving and not s.openTok then lost = true break end end end
  G.lostPolls = lost and (G.lostPolls or 0) + 1 or 0
  if G.lostPolls >= 3 then
    G.lostPolls = 0
    for _, s in pairs(G.sessions) do
      if not s.dead and not s.leaving and not s.openTok then
        if s.live then if s:reopen("libpv has no screen open") then s:goLive() end else s.lost = true end
      end
    end
  end
"""),
# 3. lifecycle flags in the session's description
("""--   dead, leaving, departed, busy, gone   lifecycle flags (see Session:event, setBusy, setGone, fallback, stop)
""",
"""--   dead, leaving, departed, busy, gone   lifecycle flags (see Session:event, setBusy, setGone, fallback, stop)
--   openWall, live, lost, reopens          when its layer was opened (os.time), its ready went, libpv lost it, how
--                                          many times it was opened again (see Session:goLive, reopen)
"""),
# 4. the open, shared with the reopen
("""--- Opens the native scene (and the shared shell scene behind it, once) and registers the session. The reply may not
--- have landed yet: the open is then settled by pollAll on a later frame. Returns false when libpv refused the scene
--- (the screen then stays stock and the spec id is remembered in G.offScreens).
function Session:open()
  local spec = self.spec
  if spec.shell then
    local t = token()
    send("pc3d:ui:open:shell|" .. spec.shell .. "|" .. t .. "|keep")
    local r = G.getenv("PRISM_UI_LOAD")
    G.shellOpen = r == nil or (type(r) == "string" and r:sub(1, 3) == "ok:")
    if not G.shellOpenLogged then G.shellOpenLogged = true; log("native: shell open -> " .. tostring(r)) end
  end
  local tok = token()
  local flags = G.dirBack and "wait,back" or "wait"
  G.dirBack = nil
  send("pc3d:ui:open:" .. self.id .. "|" .. spec.scene .. "|" .. tok .. "|" .. flags)
  local r = G.getenv("PRISM_UI_LOAD")
  local mine""",
"""--- Sends the open of the session's layer (`flags` "wait" or "wait,back"), after the shell's when the screen has one (a
--- shell still up is kept). Returns libpv's reply and this open's token (the reply is an older one while this open's
--- has not landed).
function Session:sendOpen(flags)
  local spec = self.spec
  if spec.shell then
    local t = token()
    send("pc3d:ui:open:shell|" .. spec.shell .. "|" .. t .. "|keep")
    local r = G.getenv("PRISM_UI_LOAD")
    G.shellOpen = r == nil or (type(r) == "string" and r:sub(1, 3) == "ok:")
    if not G.shellOpenLogged then G.shellOpenLogged = true; log("native: shell open -> " .. tostring(r)) end
  end
  local tok = token()
  send("pc3d:ui:open:" .. self.id .. "|" .. spec.scene .. "|" .. tok .. "|" .. flags)
  self.openWall = wall()   -- libpv drops the layer when its ready has not come 3 s after this (see Session:goLive)
  return G.getenv("PRISM_UI_LOAD"), tok
end

--- Opens the native scene (and the shared shell scene behind it, once) and registers the session. The reply may not
--- have landed yet: the open is then settled by pollAll on a later frame. Returns false when libpv refused the scene
--- (the screen then stays stock and the spec id is remembered in G.offScreens).
function Session:open()
  local spec = self.spec
  local flags = G.dirBack and "wait,back" or "wait"
  G.dirBack = nil
  local r, tok = self:sendOpen(flags)
  local mine"""),
# 5. the gates release through goLive
("""    if o ~= except and not o.dead and o.overlayGate then o.overlayGate = nil; o.readyWait = nil; send("pc3d:ui:ready:" .. o.id) end
""",
"""    if o ~= except and not o.dead and o.overlayGate then o.overlayGate = nil; o.readyWait = nil; o:goLive() end
"""),
# 6. sendReady through goLive; goLive and reopen
("""function Session:sendReady()
  self.readyWait = nil
  releaseGates(self)
  send("pc3d:ui:ready:" .. self.id)
""",
"""function Session:sendReady()
  self.readyWait = nil
  releaseGates(self)
  self:goLive()
"""),
("""--- Runs the stock Subscribe providers of the bindings the skin reads.""",
"""--- Sends the ready that starts the screen's transition. libpv drops a layer opened with "wait" whose ready has not come
--- 3 s (real time) after its open, and the shell with it when no screen is left. After a match the engine keeps this
--- thread busy or stopped for longer than that (career processing, the save): the ready of the hub and of its Match
--- Results found nothing, and the hub's stock layout, its widgets hidden for the native screen, showed black until the
--- back key left the career (R98e). So the layer is opened again first when it may be gone: its open is 3 s or more
--- back (os.time: more than 2 s; 30 s with an R98e libpv, which keeps a waiting layer while this thread does not run),
--- or a poll found libpv without any screen.
function Session:goLive()
  if self.dead then return end
  local late = self.openWall ~= nil and wall() - self.openWall >= (G.waitLimit or 3)
  if late or self.lost then
    if not self:reopen(late and ("its ready comes " .. tostring(wall() - self.openWall) .. " s after its open") or "libpv has no screen open") then return end
  end
  self.lost, self.openWall, self.live = nil, nil, true
  send("pc3d:ui:ready:" .. self.id)
end

--- Opens the session's layer again under the same id (libpv replaces whatever is left of it, the shell is opened again
--- or kept) and sends every value and list again: the new scene has none of them. Not more than 3 times a session, then
--- the screen goes back to its stock layout; also when libpv refuses the scene. Returns true when the layer is open.
function Session:reopen(why)
  if self.dead then return false end
  self.reopens = (self.reopens or 0) + 1
  if self.reopens > 3 then log(tostring(self.spec.id) .. ": lost natively again (" .. why .. "), back to its stock layout"); self:fallback("lost natively"); return false end
  log(tostring(self.spec.id) .. " opens again natively (" .. why .. ")")
  local r, tok = self:sendOpen("wait")
  if type(r) == "string" and r:sub(-#tok - 1) == ":" .. tok and r:sub(1, 3) ~= "ok:" then
    local refused = r:match("^err:(.*):[^:]*$") or r
    log("native: " .. tostring(self.spec.id) .. " did not open again (" .. tostring(refused) .. ")")
    self:fallback(refused)
    return false
  end
  self.last = {}
  for k in pairs(G) do if type(k) == "string" and k:sub(1, 6) == "shell:" then G[k] = nil end end   -- the shell's values, if it went too
  self:flush(true)
  return true
end

--- Runs the stock Subscribe providers of the bindings the skin reads."""),
# 7. the gates also end by real time
("""  if self.readyWait then self.readyWait = self.readyWait + 1; if #self.providers == 0 or self.readyWait >= 12 then self:sendReady() end end
  if self.overlayGate then
    self.overlayGate = self.overlayGate + 1
    if self.overlayGate > 45 then
      self.overlayGate = nil
      log(tostring(self.spec.id) .. ": its overlay did not come natively in 45 frames, shown alone")
      if #self.providers == 0 then self:sendReady() else self.readyWait = 0 end
    end
  end
""",
"""  -- The gates count frames, and libpv waits 3 s of real time for a ready: after a match the engine runs this thread at a
  -- few frames a second, so a screen comes on 2 s after its open (os.time: 1 to 2 s) whatever the counts say.
  local due = self.openWall ~= nil and wall() - self.openWall >= 2
  if self.readyWait then self.readyWait = self.readyWait + 1; if #self.providers == 0 or self.readyWait >= 12 or due then self:sendReady() end end
  if self.overlayGate then
    self.overlayGate = self.overlayGate + 1
    if self.overlayGate > 45 or due then
      self.overlayGate = nil
      log(tostring(self.spec.id) .. ": its overlay did not come natively in " .. (due and "2 s" or "45 frames") .. ", shown alone")
      if #self.providers == 0 or due then self:sendReady() else self.readyWait = 0 end
    end
  end
"""),
# 8. hello: an R98e libpv keeps a waiting layer while this thread does not run
("""  if h:find(";gl=-1", 1, true) or h:find(";touch=-1", 1, true) then G.off = "native reported " .. h; log("native: unavailable (" .. h .. ")"); return false end
""",
"""  if h:find(";gl=-1", 1, true) or h:find(";touch=-1", 1, true) then G.off = "native reported " .. h; log("native: unavailable (" .. h .. ")"); return false end
  -- "waitpolls" (R98e libpv): a layer waiting for its ready is dropped only once this thread had its frames, or after
  -- 30 s; an older libpv drops it 3 s after its open whatever this thread did (see Session:goLive)
  G.waitLimit = h:find("waitpolls", 1, true) and 30 or 3
"""),
]

for path in sys.argv[1:]:
    s = open(path, encoding='utf-8').read()
    for old, new in EDITS:
        n = s.count(old)
        assert n == 1, '%s: anchor found %d times: %r' % (path, n, old[:80])
        s = s.replace(old, new)
    open(path, 'w', encoding='utf-8').write(s)
    print('patched', path)
