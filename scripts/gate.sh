#!/usr/bin/env bash
# The push gate: everything CI runs, with exit codes checked directly (a pipe into tail once hid
# a failing Lighthouse step and put main red; see docs/log.md, v2 Phase 6).
#   CHROME_PATH=/path/to/chrome scripts/gate.sh [--skip-lighthouse]
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
fail=0
step() { local name="$1"; shift; "$@" > "/tmp/gate-${name// /_}.log" 2>&1; local rc=$?
  if [ $rc -ne 0 ]; then echo "FAIL  $name (exit $rc), see /tmp/gate-${name// /_}.log"; fail=1; else echo "ok    $name"; fi; }
step ruff ruff check .
step pytest python -m pytest -q
# Not in a subshell: `fail` must survive.
cd web
step "web check" npm run check
step "web lint" npm run lint
step "web test" npm test
step "web build" npm run build
step "web size" npm run size
if [ "${1:-}" != "--skip-lighthouse" ]; then step lighthouse npm run lighthouse; fi
cd ..
exit $fail
