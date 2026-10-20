"""arm_emu_r98e.py - R98e on the BUILT ARM libpv.so (unicorn, the rig of arm_emu4.py): a layer opened with "wait" is
kept while the game's Lua thread does not run, and still dropped when Lua runs and never sends its ready.

  venv/bin/python -I tests/native/arm_emu_r98e.py <libpv.so> <ux dir with prism/skins/*.pn + fonts> <fixture.json> [chain]

The poll reply's first flag ("s1" / "s0") says whether libpv has an open layer; a waiting layer counts, and no shell
is opened here, so it says whether the waiting layer is still there. Every PRISM_UI_EV read is one Lua poll.
1. hello: the R98e libpv says "waitpolls" in its caps (PrismSkin then waits 30 s before it opens a late screen again)
2. no poll for 10 s (the Lua thread stopped after a match): the waiting layer is still there; after 30 s it is dropped
3. Lua polls every frame and never sends the ready: dropped after 3 s, as before
4. a ready that comes after 12 s without polls finds its layer, which then draws
Prints PASS/FAIL lines; exit status 1 on failure.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'arm_emu4.py'), encoding='utf-8').read()
# reuse arm_emu4.py's emulator (everything before its session)
exec(src.split('# ------------------------------------------------------------------ the session')[0])

def any_open(): return ENV.get('PRISM_UI_EV', '')[1:2] == '1'   # one poll
def frames(seconds): swap(int(round(seconds * 60)))

swap(31)
command('pc3d:ui:hello:r1')
check('waitpolls' in ENV.get('PRISM_UI', '').split(';caps=')[-1].split(';')[0], '1. hello caps say waitpolls: ' + ENV.get('PRISM_UI', '')[:110])

command('pc3d:ui:open:W#1|prism/skins/MatchResults.pn|t1|wait')
check(ENV.get('PRISM_UI_LOAD', '') == 'ok:W#1:t1', '2. a layer opens with wait: ' + ENV.get('PRISM_UI_LOAD', ''))
frames(10.0)
at10 = any_open()
frames(21.0)
check(at10 and not any_open(), '2. no Lua poll for 10 s: the waiting layer is still there (%s); after 31 s it is dropped (%s)' % (at10, any_open()))

command('pc3d:ui:open:W#2|prism/skins/MatchResults.pn|t2|wait')
for _ in range(150):
    ENV.get('PRISM_UI_EV'); swap(1)
at25 = any_open()
for _ in range(60):
    ENV.get('PRISM_UI_EV'); swap(1)
check(at25 and not any_open(), '3. Lua polls every frame, no ready: there at 2.5 s (%s), dropped by 3.5 s (%s)' % (at25, any_open()))

command('pc3d:ui:open:W#3|prism/skins/MatchResults.pn|t3|wait')
frames(12.0)
command('pc3d:ui:ready:W#3')
d0 = len(GL['draws']); swap(30); drawn = len(GL['draws']) - d0
check(any_open() and drawn > 0, '4. a ready 12 s late (Lua stopped) finds its layer, and it draws: %d GL draws in 30 frames' % drawn)

print('ALL PASS' if not FAILS else '%d FAILED' % len(FAILS))
sys.exit(1 if FAILS else 0)
