#!/bin/sh
# Runs the Player Career host tests on Lua 5.1. usage: sh tests/run_tests.sh <lua5.1 binary> <ux dir>
set -e
LUA=${1:-lua5.1}; UX=${2:-ux}
D=$(dirname "$0")
for t in test_prismpro test_popup_setup test_flow; do
  printf '%-18s ' "$t"; "$LUA" "$D/$t.lua" "$UX" | tail -n 1
done
