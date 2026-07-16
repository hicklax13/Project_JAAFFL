#!/usr/bin/env bash
# JAAFFL SessionStart bootstrap — installs deps and runs quick lint/test health checks.
# Emits one summary line; each step is a no-op when already satisfied.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 0

PY="$(pwd)/.venv/Scripts/python.exe"
[ -e "$PY" ] || PY="$(pwd)/.venv/bin/python"

status=()

if [ ! -e "$PY" ] && command -v uv >/dev/null 2>&1; then
  uv venv .venv --python 3.12 >/dev/null 2>&1
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$PY" -e "./backend[dev,data]" >/dev/null 2>&1 \
    && status+=("backend-deps:ok") || status+=("backend-deps:FAIL")
else
  "$PY" -m pip install --quiet -e "./backend[dev,data]" >/dev/null 2>&1 \
    && status+=("backend-deps:ok") || status+=("backend-deps:FAIL")
fi

if command -v pnpm >/dev/null 2>&1; then
  pnpm install --prefer-offline --silent >/dev/null 2>&1 \
    && status+=("js-deps:ok") || status+=("js-deps:FAIL")
fi

"$PY" -m ruff check backend >/dev/null 2>&1 && status+=("ruff:ok") || status+=("ruff:FAIL")
(cd backend && "$PY" -m pytest -q >/dev/null 2>&1) && status+=("pytest:ok") || status+=("pytest:FAIL")
pnpm -r --silent typecheck >/dev/null 2>&1 && status+=("tsc:ok") || status+=("tsc:FAIL")

echo "JAAFFL session bootstrap: ${status[*]}"
