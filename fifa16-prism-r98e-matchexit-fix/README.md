## R98e: no black screen after a match (on top of R98d PT-BR)

**Install:** copy `INSTALL-ON-PHONE/ux` over your ux folder. The R97 APK stays. That alone ends the stuck black screen.
With the R97 libpv there can still be black for the seconds the game is busy after the match, then the hub comes back
on its own.

**Optional, the libpv half:** put `libpv-r98e/libpv.so` into the R97 APK as `lib/armeabi-v7a/libpv.so`, then sign the APK
with your V7 key the way you made R97. It's your libpv-source built with the two-file patch below. Nothing else in the
APK changes. With it the screens aren't dropped at all: the career room stays up while the game works, with no black
in between.

`libpv-r98e/libpv.so`: sha256 `3065a07aef11fdd3eae0f86fecfe8e85a71083d477eab163691f39e5d1386b77`, 891656 bytes, ARMv7,
same exports and the same NEEDED libraries as the R97 libpv.

### What was wrong (preview.log, both black screens)
- After a match the hub (`MatchSelect`) opens **Match Results** from its constructor and waits for it, so both come on
  together. Both layers are opened with `wait` and start once PrismSkin sends `ready`.
- **libpv drops a waiting layer 3 s after its open, in real time** (`pn_core.c`, `layers_update`). PrismSkin counted its
  gates in **frames of the game's Lua thread**: 45 for the overlay gate, up to 12 more while the stock providers retry.
- Right after a match the game keeps that thread **busy or stopped for seconds**, between career processing and the save:
  - a played match: 9 Lua frames in 18 s (`perf: 9 frames ... stock update 88.93 ms`);
  - a simulated match: 15 frames in 6 s.
- So the 3 s ran out first:
  `open: layer never became ready, dropped: MatchSelect` / `... dropped: MatchResults` → `shell removed with the last screen`.
- PrismSkin's `ready` came afterwards and found nothing. The Lua side never found out. The hub's **stock** layout stayed
  hidden for the native screen (`bnd_prism_zinc` off), so the game drew black: `probe: ... (ALL BLACK)`.
- It stayed black **for good**. In your last session Lua was back at ~57 fps a second after the drop, and the screen was
  still black 17 s later, when the log ends. In the other one it lasted until the career was left for the main menu,
  25 s later.
- "Sometimes" = only when the game happens to stall long enough after the match. Some match days it doesn't, and the
  same flow works (the R98d log has one of those just before the second black screen).

### Now
**PrismSkin.lua** (works with the R97 libpv):
- **The gates also end by real time.** A screen goes `ready` at the latest 2 s after its open (`os.time`, so 1 to 2 s),
  whatever the frame counts say. At a few frames a second the hub now comes on before libpv's limit. If Match Results
  isn't there yet, the hub comes on alone and the results arrive on top a moment later.
- **A late ready opens its layer again first.** If the ready comes 3 s or more after the open (the Lua thread stopped),
  the layer is opened again under the same id, all its values and lists are sent again, then it goes `ready`. The log
  says `MatchSelect opens again natively (its ready comes 17 s after its open)`.
- **libpv without any screen under live screens comes back.** If 3 polls in a row say `s0` (libpv has nothing open)
  while sessions are live, those sessions open again. A screen lost 3 times goes back to its stock layout: you'd see
  the stock screen, never black.

**libpv** (`pn_core.c`, `pn_int.h`, the same file in `project/native` and `libpv-source`):
- A waiting layer is dropped only after **3 s and 180 Lua polls** (every live screen polls once a frame), **or after
  30 s whatever happens**:
  - a stopped Lua thread doesn't use up the time, so the hub, the results and the career room stay up behind it;
  - an open nobody finishes while Lua runs is still dropped after 3 s, as before.
- `hello` now lists `waitpolls` in its caps. PrismSkin then waits 30 s instead of 3 before it opens a late screen
  again, so with this libpv nothing is opened twice.

### Tests
- `project/tests/test_r98e_matchexit.py`: the real `PrismSkin.lua` (Lua 5.1) driving the real Prism Native C
  (`libpnhost.so` on ANGLE/SwiftShader), with the game's Lua thread and the render thread run separately. The stand-in
  screens are built like the engine builds them, and their providers fail at first like Match Results' do.
  - **1.** the Lua thread stops for 16 s after a played match: the hub, the results and the room are up afterwards;
  - **2.** the Lua thread runs at 2.5 fps and the results open 2.8 s after the hub: both come on;
  - **3.** a normal exit at 60 fps: the hub and the results come on together in one go (R68 behaviour), each opened once;
  - **4.** every native layer gone under live screens: they open again within a few frames;
  - **5.** (R98e libpv) a waiting layer survives 10 s of a stopped Lua thread, is dropped after 30 s, is still dropped
    after 3 s when Lua polls but never sends ready, and a ready 12 s late finds its layer.
- `project/tests/native/arm_emu_r98e.py`: section 5 again, on the **built ARM libpv.so** in the unicorn emulator
  (the arm_emu4.py rig), plus the `waitpolls` cap in the hello reply.
- Results:

  | PrismSkin | libpv | test_r98e_matchexit | arm_emu_r98e |
  |---|---|---|---|
  | R98d | R97 | **1, 2 and 4 fail**: the same drops as your log | 3 failed: the late ready draws **0 GL calls** |
  | R98e | R97 | all pass (`--libpv-r97`, sections 1-4) | |
  | R98e | R98e | all pass, nothing opened twice | all pass |

- Still passing: `test_r68.py` and `test_r69.py` (both PrismSkin copies), `tests/native/host_gl.py`. `arm_emu4.py`
  gives the same 8 failures on the R97 libpv as on R98e: they come from its fixture, not this change.
- Not run here: the suites that need your stock ux folder, player database and libf16store.so (`run_r9x_suites.sh`).
  `test_r68.py`/`test_r69.py` cover the parts of PrismSkin this touches, but run those on your machine too.
- `run_all.sh` now runs both new tests.

### Other builds (English, locked)
`project/ux/lua/prism/PrismSkin.lua` is the patched source, so a rebuild (`node tools/prismc.js build`) carries the fix
into every variant. To patch an already-built `PrismSkin.lua` directly: `python3 tools/r98e_patch_prismskin.py <file>`.
It changes only shared code and refuses to run if an anchor isn't found exactly once.
`tools/r98e_patch_native.py <dir with pn_core.c + pn_int.h>` does the same for the C.

### Files
- `INSTALL-ON-PHONE/ux/lua/prism/PrismSkin.lua`: the pt-BR build, drop-in.
- `project/...`, `libpv-source/...`: the changed sources and tests, at their place in the R98d package.
- `project/native/host/pnhost.c`: two test hooks (`pnt_layer_state`, `pnt_quads`) for the PC harness, not in libpv.
- `patches/R98e-from-R98d-PT-BR.diff`: everything above as one diff (`patch -p1` from the package root).

### If it ever happens again
Send `preview.log`. The new lines to look for are `opens again natively (...)`, `its overlay did not come natively in
2 s, shown alone` and `lost natively again`. With the R98e libpv, `hello: ok;v=4.0.0;...;caps=...,waitpolls` confirms
it's installed.
