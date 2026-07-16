#!/usr/bin/env bash
# JAAFFL SessionStart bootstrap — installs deps and runs quick lint/test health checks.
# The backend and JS chains run in parallel; expect ~10-40s warm (installs re-resolve
# even when satisfied). Emits one summary line.
set -u
cd "$(dirname "$0")/../.." || exit 0

PY="$(pwd)/.venv/Scripts/python.exe"
[ -e "$PY" ] || PY="$(pwd)/.venv/bin/python"

if [ ! -e "$PY" ] && command -v uv >/dev/null 2>&1; then
  uv venv .venv --python 3.12 >/dev/null 2>&1
fi

step() {
  local name=$1
  shift
  "$@" >/dev/null 2>&1 && echo "$name:ok" || echo "$name:FAIL"
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

(
  if command -v uv >/dev/null 2>&1; then
    step backend-deps uv pip install --quiet --python "$PY" -e "./backend[dev,data]"
  else
    step backend-deps "$PY" -m pip install --quiet -e "./backend[dev,data]"
  fi
  step ruff "$PY" -m ruff check backend
  step pytest "$PY" -m pytest -q backend/tests
) > "$tmp/backend" &

(
  if command -v pnpm >/dev/null 2>&1; then
    step js-deps pnpm install --prefer-offline --silent
    step tsc pnpm -r --silent typecheck
  fi
) > "$tmp/js" &

wait
echo "JAAFFL session bootstrap: $(cat "$tmp/backend" "$tmp/js" | tr '\n' ' ')"
