#!/usr/bin/env bash
# Runs every Prism check against a game ux folder.
#   tests/run_all.sh <game ux dir>   (the folder with Default.constants; Prism is installed into a temp copy)
# Needs: node, python3 with lupa (pip install lupa), clang (Prism Native wasm + host builds).
# Optional: playwright (browser test), Chromium's ANGLE (Prism Native GPU tests; set ANGLE_DIR if it is not the
# Playwright one), PRISM_LIBPV=/path/to/libpv.so + PRISM_EMU_PY=/python/with/unicorn+pyelftools (runs the ARM
# libpv build in an emulator), and the R55 package's patch-sources/fe_test.py (FE_TEST=...) for the legacy suite.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
UX="${1:?usage: tests/run_all.sh <game ux dir>}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
filter() { grep -v -E '^\s*(\[C\]|\[string|stack traceback|\(tail call\))' || true; }

echo "== build";              node "$HERE/tools/prismc.js" build --ux "$UX"
cp -a "$UX" "$TMP/ux"; cp -a "$HERE/ux/." "$TMP/ux/"; cp -a "$HERE/assets" "$TMP/assets"
if [ -d "$HERE/../INSTALL-ON-PHONE/ux/flows/mainflow" ]; then cp -a "$HERE/../INSTALL-ON-PHONE/ux/flows/mainflow/." "$TMP/ux/flows/mainflow/"; fi
echo "== compiler";           node "$HERE/tests/test_compiler.js" | tail -1
echo "== expression parity";  python3 "$HERE/tests/test_expr_parity.py" | tail -2
echo "== runtime v1";         python3 "$HERE/tests/test_runtime.py" 2>&1 | filter | tail -1
echo "== runtime v2 (FC)";    python3 "$HERE/tests/test_runtime_v2.py" "$TMP/ux" 2>&1 | filter | tail -1
echo "== hybrid wiring";      python3 "$HERE/tests/test_hybrid.py" "$TMP/ux" | tail -1
echo "== validator";          node "$HERE/tests/test_validate.js" "$TMP/ux" | tail -1
echo "== Prism Native build";   sh "$HERE/native/build.sh" | sed 's/^/   /'
if [ -f "${ANGLE_DIR:-/opt/pw-browsers/chromium-1194/chrome-linux}/libGLESv2.so" ]; then
  echo "== Prism Native e2e (Lua <-> native C <-> GLES)"; python3 "$HERE/tests/test_native_e2e.py" "$TMP/ux" "$HERE/native/build/libpnhost.so" 2>&1 | grep -E "FAIL|ALL PASS|FAILED"
  echo "== R98e match exit (the Lua thread stopped / slow)"; python3 "$HERE/tests/test_r98e_matchexit.py" "$TMP/ux" "$HERE/native/build/libpnhost.so" 2>/dev/null | grep -E "FAIL|ALL PASS|FAILED"
fi
if [ -n "${PRISM_LIBPV:-}" ] && [ -n "${PRISM_EMU_PY:-}" ]; then
  echo "== libpv ARM build in the emulator"
  node "$HERE/tests/native/scene_script.js" "$TMP/ux" CareerHub "$TMP/ch.txt" "$TMP/x.ppm" 1 >/dev/null && grep '^vals ' "$TMP/ch.txt" | sed 's/^vals //' > "$TMP/ch_vals.txt"
  "$PRISM_EMU_PY" "$HERE/tests/native/arm_emu.py" "$PRISM_LIBPV" "$TMP/ux" "$TMP/ch_vals.txt" 2>&1 | grep -E "FAIL|ALL PASS|FAILED|instructions"
  "$PRISM_EMU_PY" "$HERE/tests/native/arm_emu_r98e.py" "$PRISM_LIBPV" "$TMP/ux" "$HERE/tests/native/fixtures/Standings.scan.json" chain 2>&1 | grep -E "FAIL|ALL PASS|FAILED"
fi
echo "== validate tree";      node "$HERE/tools/prismc.js" validate --ux "$TMP/ux" | sed -n '1,4p'
PV="$HERE/preview/prism-preview.html"; [ -f "$PV" ] || PV="$HERE/../prism-preview.html"
if [ -f "$PV" ]; then echo "== previewer (browser)"; node "$HERE/tests/test_preview.js" "$PV" | tail -1; fi
FE="${FE_TEST:-$HERE/../R55/patch-sources/fe_test.py}"
if [ -f "$FE" ]; then echo "== legacy front end (fe_test.py)"; python3 -I "$FE" "$TMP/ux/flows/mainflow" | grep -v '^\[F16\]' | tail -1; fi
echo "== all checks finished"
