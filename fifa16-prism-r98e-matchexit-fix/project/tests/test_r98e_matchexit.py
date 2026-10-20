"""test_r98e_matchexit.py - R98e: no black screen when the career hub comes back after a match.

The REAL PrismSkin.lua (Lua 5.1) drives the REAL Prism Native C (libpnhost.so on ANGLE/SwiftShader) through the same
F16Service channel as the phone, with the engine's two threads played separately: the game's Lua thread (screen
updates, the only place PrismSkin runs) and the render thread (eglSwapBuffers: libpv's frame, its timeouts).

  venv/bin/python -I tests/test_r98e_matchexit.py <ux with prism/skins> <libpnhost.so> [PrismSkin.lua] [--libpv-r97]

The bug (preview.log, R98d): after a match the hub (MatchSelect) opens Match Results from its constructor and waits for
it, both opened with "wait". libpv drops a waiting layer 3 s (real time) after its open; PrismSkin counted its gates in
FRAMES of the Lua thread, which the engine keeps busy or stopped for seconds after a match (career processing, the save).
Both layers were dropped, the shell went with them, the ready that came later found nothing, and the stock layout under
the hub (widgets hidden for the native screen) showed black until the back key left the career.

1. the Lua thread stops for 16 s after the hub opens and the results open (a played match): the hub and the results
   come on once it runs again
2. the Lua thread runs at 2.5 fps and the results open 2.8 s after the hub (a simulated match): both come on
3. a normal exit (60 fps): the hub and the results come on together in one go, and nothing is opened twice
4. libpv lost a screen that was already up: PrismSkin opens it again within a few frames
5. (libpv R98e only) a waiting layer is kept while the Lua thread does not run, and still dropped when the Lua thread
   runs and never sends its ready (or after 30 s whatever happens)

--libpv-r97: the native lib is the R97 one (without the libpv side of the fix): section 5 is skipped, sections 1-4 must
pass on the PrismSkin side alone.
"""
import ctypes, os, sys
import lupa.lua51 as lupa

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
R97 = '--libpv-r97' in sys.argv
UX, LIB = ARGS[0], ARGS[1]
SKIN = ARGS[2] if len(ARGS) > 2 else os.path.join(UX, 'lua/prism/PrismSkin.lua')
FAILS = []
W, H = 780, 360     # the phone's 2340x1080 / 3: software GL, and only layer states are checked
FPS = 60.0          # the Lua thread's frame rate
RFPS = 20.0         # the render thread's while the Lua thread does not run (libpv's timeouts are real time)


def check(c, m):
    print(('  PASS  ' if c else '  FAIL  ') + m)
    if not c:
        FAILS.append(m)


pn = ctypes.CDLL(LIB)
pn.pnt_init.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
pn.pnt_command.argtypes = [ctypes.c_char_p]
pn.pnt_frames.argtypes = [ctypes.c_int, ctypes.c_double]
pn.pnt_time.restype = ctypes.c_double
pn.pnt_poll_env.argtypes = [ctypes.c_char_p, ctypes.c_uint]
pn.pnt_layer_state.argtypes = [ctypes.c_char_p]
assert pn.pnt_init(W, H, (os.path.abspath(UX) + '/').encode()) == 0, 'GL init failed'
libc = ctypes.CDLL(None)
libc.getenv.restype = ctypes.c_char_p
POLLBUF = ctypes.create_string_buffer(6400)
CMDS = []


def exec_cmd(c):
    c = str(c)
    CMDS.append(c)
    if c.startswith('pc3d:ui:'):
        pn.pnt_command(c[5:].encode('utf-8'))
    return 0


def pyenv(k):
    k = str(k)
    if k == 'PRISM_UI_EV':   # libpv answers the per-frame poll itself (os.getenv hook)
        pn.pnt_poll_env(POLLBUF, 6400)
        return POLLBUF.value.decode('utf-8', 'replace')
    v = libc.getenv(k.encode())
    return v.decode('utf-8', 'replace') if v else None


def state(layer): return chr(pn.pnt_layer_state(str(layer).encode()))
def render(seconds):   # the render thread alone
    n = max(1, int(round(seconds * RFPS)))
    pn.pnt_frames(n, seconds / n)


L = lupa.LuaRuntime(unpack_returned_tuples=True)
g = L.globals()
g.PYEXEC = exec_cmd
g.PYENV = pyenv
g.PYREAD = lambda p: open(str(p), encoding='utf-8').read()
g.NOW = lambda: pn.pnt_time()
g.SKINFILE = SKIN
L.execute(r'''
F16_OUT = ""
F16 = { Cmd = function(c) c = tostring(c); if c:sub(1, 4) == "env:" then local v = PYENV(c:sub(5)); F16_OUT = (v == nil) and "\1" or tostring(v) else PYEXEC(c); F16_OUT = "" end end,
        Out = function() return F16_OUT end,
        Tick = function(n) local v = PYENV("PRISM_UI_EV"); return v == nil and "" or tostring(v) end }
-- the phone's clocks: os.time is real time in whole seconds (the test's clock is libpv's), os.clock process cpu time
os.time = function() return 1700000000 + math.floor(NOW()) end
LOGS = {}
print = function(...) local t = {} for i = 1, select('#', ...) do t[#t + 1] = tostring((select(i, ...))) end LOGS[#LOGS + 1] = table.concat(t, ' ') end
Skin = assert(loadstring(PYREAD(SKINFILE), '@PrismSkin.lua'))()
local api = function(name) if name == 'F16Service' then return F16 end return {} end
function MKIM()
  local im = { pub = {}, subs = {}, acts = {} }
  im.Publish = function(b, v) im.pub[b] = v end
  im.Subscribe = function(b, fn) im.subs[#im.subs + 1] = { b, fn } end
  im.Unsubscribe = function() end
  im.Refresh = function() end
  im.RegisterAction = function(a, fn) im.acts[a] = fn end
  im.RegisterDataAction = function(b, a, fn) im.acts[a] = fn end
  im.UnregisterAction = function(a) im.acts[a] = nil end
  return im
end
function MKNAV() return { Event = function() end } end
-- stand-in screens built the way the engine builds them (test_r68.py), on the real compiled scenes
function SCREEN(id, opts)
  opts = opts or {}
  local C = {}
  C.__index = C
  function C.new(cls, init)
    local o = setmetatable({ im = init.im, nav = init.nav }, cls)
    -- the stock idiom (Subscribe, then Publish); the provider needs state the screen sets later and fails its first
    -- opts.failFor calls, as Match Results' do: the screen's ready waits for them (Session.readyWait)
    local calls = 0
    o.im.Subscribe('bnd_title', function() calls = calls + 1; if calls <= (opts.failFor or 0) then error('not yet') end; o.im.Publish('bnd_title', id) end)
    o.im.Publish('bnd_title', id)
    if opts.onNew then opts.onNew(o) end
    return o
  end
  function C.update() end
  function C.finalize() end
  local spec = { id = id, scene = 'prism/skins/' .. id .. '.pn', shell = opts.shell, pass = { bnd_title = 'title' }, actions = {}, zinc = {} }
  return Skin.wrap(C, spec), spec
end
function OPEN(W) local im = MKIM(); local o = W:new({ im = im, nav = MKNAV(), api = api }); return o, im end
function LAYER(o) local s = rawget(o, '__pskin'); return s and s.id end
-- the hub after a match: opens the results overlay from its constructor
HubW = SCREEN('MatchSelect', { shell = 'prism/skins/CareerShell.pn', failFor = 2, onNew = function(o) o.nav.Event(nil, 'evt_show_overlay', { vvm = 'MatchResults.vvm' }) end })
ResW = SCREEN('MatchResults', { failFor = 10 })
LIVE = {}
function LUAFRAME() for _, o in ipairs(LIVE) do o:update(1 / 60) end end
function LOGHAS(s) for _, l in ipairs(LOGS) do if l:find(s, 1, true) then return true end end return false end
''')


def lua_frame(render_after=1.0 / FPS):
    """one frame of the game's Lua thread (every live screen updates), then the render thread until the next one"""
    L.execute('LUAFRAME()')
    render(render_after)


def open_screen(var, cls):
    L.execute('%s, %sIM = OPEN(%s); LIVE[#LIVE + 1] = %s' % (var, var, cls, var))
    return L.eval('LAYER(%s)' % var)


def close_all():
    L.execute('for _, o in ipairs(LIVE) do o:finalize() end; LIVE = {}')
    render(2.0)


def opened(layer): return sum(1 for c in CMDS if c.startswith('pc3d:ui:open:%s|' % layer))


ok_start = L.eval('Skin ~= nil')
check(bool(ok_start), 'PrismSkin.lua loaded: %s' % SKIN)

# ---------------------------------------------------------------- 1. the Lua thread stops after a played match
hub = open_screen('HUB1', 'HubW')
lua_frame()
render(1.4)                       # the engine works, only the render thread runs
res = open_screen('RES1', 'ResW')
lua_frame()
render(16.0)                      # career processing: the Lua thread stops for 16 s
for _ in range(30):
    lua_frame()
check(state(hub) == 'O' and state(res) == 'O',
      '1. Lua thread stopped 16 s after a played match: the hub and the results are on screen once it runs again (hub %s, results %s)' % (state(hub), state(res)))
check(state('shell') == 'O', '1. the career room (shell) is back behind them (shell %s)' % state('shell'))
wl = L.eval('Skin.G.waitLimit')
if R97:
    check(wl == 3, '1. an R97 libpv (no "waitpolls" in its hello): PrismSkin opens a screen again when its ready is 3 s late (%s)' % wl)
else:
    check(wl == 30 and opened(hub) == 1 and opened(res) == 1,
          '1. libpv kept both layers through the stop ("waitpolls"): nothing was opened twice (limit %s, hub x%d, results x%d)' % (wl, opened(hub), opened(res)))
close_all()

# ---------------------------------------------------------------- 2. the Lua thread at 2.5 fps after a simulated match
hub = open_screen('HUB2', 'HubW')
lua_frame(0.4)
for _ in range(6):                # 2.8 s at 2.5 fps: Match Sim leaves, the results open late
    lua_frame(0.4)
res = open_screen('RES2', 'ResW')
for _ in range(15):               # 6 s more at 2.5 fps
    lua_frame(0.4)
for _ in range(60):
    lua_frame()
check(state(hub) == 'O' and state(res) == 'O',
      '2. Lua thread at 2.5 fps, the results 2.8 s after the hub: both on screen (hub %s, results %s)' % (state(hub), state(res)))
check(state('shell') == 'O', '2. the shell is up behind them (shell %s)' % state('shell'))
close_all()

# ---------------------------------------------------------------- 3. a normal exit at 60 fps
n0 = len(CMDS)
hub = open_screen('HUB3', 'HubW')
lua_frame(); lua_frame(); lua_frame()
early = any(c == 'pc3d:ui:ready:' + hub for c in CMDS[n0:])
res = open_screen('RES3', 'ResW')
for _ in range(20):
    lua_frame()
c3 = CMDS[n0:]
ri = [i for i, c in enumerate(c3) if c in ('pc3d:ui:ready:' + hub, 'pc3d:ui:ready:' + res)]
check(not early and len(ri) == 2 and c3[ri[0]] == 'pc3d:ui:ready:' + hub and ri[1] - ri[0] <= 2,
      '3. normal exit: the hub is not shown before the results, then both come on in one go (R68 behaviour kept)')
check(state(hub) == 'O' and state(res) == 'O' and opened(hub) == 1 and opened(res) == 1,
      '3. both on screen, each opened once (hub %s x%d, results %s x%d)' % (state(hub), opened(hub), state(res), opened(res)))
close_all()

# ---------------------------------------------------------------- 4. libpv lost a screen that was already up
hub = open_screen('HUB4', 'HubW')
res = open_screen('RES4', 'ResW')
for _ in range(10):
    lua_frame()
before = state(hub), state(res)
pn.pnt_command(('ui:close:' + res).encode()); pn.pnt_command(('ui:close:' + hub).encode()); pn.pnt_command(b'ui:close:shell')
render(0.5)
for _ in range(10):
    lua_frame()
check(before == ('O', 'O') and state(hub) == 'O' and state(res) == 'O' and state('shell') == 'O',
      '4. every native layer gone under live screens: PrismSkin opens them again (before %s, now hub %s, results %s, shell %s)' % (before, state(hub), state(res), state('shell')))
close_all()

# ---------------------------------------------------------------- 5. libpv: the waiting deadline counts the Lua thread's polls
if R97:
    print('  SKIP  5. libpv waiting deadline (--libpv-r97)')
else:
    pn.pnt_command(b'ui:open:W5|prism/skins/MatchResults.pn|t5|wait')
    render(10.0)                  # no poll: the Lua thread is stopped
    s10 = state('W5')
    render(21.0)
    check(s10 == 'w' and state('W5') == '-', '5. a waiting layer is kept while the Lua thread is stopped (10 s: %s) and dropped after 30 s (%s)' % (s10, state('W5')))
    pn.pnt_command(b'ui:open:W6|prism/skins/MatchResults.pn|t6|wait')
    for _ in range(int(2.5 * FPS)):
        pn.pnt_poll_env(POLLBUF, 6400); render(1.0 / FPS)
    s25 = state('W6')
    for _ in range(int(1.0 * FPS)):
        pn.pnt_poll_env(POLLBUF, 6400); render(1.0 / FPS)
    check(s25 == 'w' and state('W6') == '-', '5. the Lua thread runs and polls but never sends the ready: dropped after 3 s as before (2.5 s: %s, 3.5 s: %s)' % (s25, state('W6')))
    pn.pnt_command(b'ui:open:W7|prism/skins/MatchResults.pn|t7|wait')
    render(12.0)
    pn.pnt_command(b'ui:ready:W7')
    render(0.5)
    check(state('W7') == 'O', '5. a ready that comes after 12 s of a stopped Lua thread still finds its layer (%s)' % state('W7'))
    pn.pnt_command(b'ui:close:W7')

logs = list(L.eval('LOGS').values())
errs = [l for l in logs if 'error in' in l]
check(not errs, 'no Lua errors in PrismSkin: %s' % errs[:3])
print('ALL PASS' if not FAILS else '%d FAILED' % len(FAILS))
sys.stdout.flush()
os._exit(1 if FAILS else 0)   # no interpreter teardown: ANGLE's own crashes there
