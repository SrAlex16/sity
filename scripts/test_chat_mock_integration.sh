#!/usr/bin/env bash
# Run the chat tool registry integration test against a local mock backend.
#
# Does NOT modify the system service. Launches a temporary uvicorn on port 8010
# with SITY_AI_PROVIDER=mock and SITY_DAILY_TOKEN_HARD_CAP=false, runs the
# integration test, then stops the backend.
#
# Usage (local, with venv):
#   ./scripts/test_chat_mock_integration.sh
#
# Usage (CI, pip-installed globally):
#   ./scripts/test_chat_mock_integration.sh  (same command)
#
# The script uses backend/.venv/bin/uvicorn when available (local dev),
# and falls back to uvicorn from PATH (CI / global pip install).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$ROOT/backend"
MOCK_PORT=8010
MOCK_URL="http://127.0.0.1:$MOCK_PORT"
UVICORN_LOG="$(mktemp /tmp/sity-mock-backend.XXXXXX.log)"

# Prefer the project venv; fall back to whatever is in PATH (CI).
if [[ -x "$BACKEND/.venv/bin/uvicorn" ]]; then
  UVICORN="$BACKEND/.venv/bin/uvicorn"
else
  UVICORN="uvicorn"
fi

cleanup() {
  if [[ -n "${MOCK_PID:-}" ]]; then
    kill "$MOCK_PID" 2>/dev/null || true
  fi
  pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $MOCK_PORT" 2>/dev/null || true
  rm -f "$UVICORN_LOG"
}
trap cleanup EXIT

printf '==> Starting mock backend on %s\n' "$MOCK_URL"

cd "$BACKEND"
env \
  SITY_AI_PROVIDER=mock \
  SITY_DAILY_TOKEN_HARD_CAP=false \
  "$UVICORN" app.main:app \
    --host 127.0.0.1 --port "$MOCK_PORT" \
    --no-access-log \
    > "$UVICORN_LOG" 2>&1 &

MOCK_PID=$!

# Wait for backend to be ready (up to 30s — CI runners can be slower).
for i in $(seq 1 30); do
  if curl -fsS "$MOCK_URL/health" >/dev/null 2>&1; then
    printf '[OK] Mock backend ready (%ds)\n' "$i"
    break
  fi
  sleep 1
  if [[ "$i" -eq 30 ]]; then
    echo '[FAIL] Mock backend did not start in 30s'
    cat "$UVICORN_LOG"
    exit 1
  fi
done

printf '==> Running integration test suite\n\n'
cd "$ROOT"
SITY_TEST_BASE_URL="$MOCK_URL" ./scripts/test_chat_tool_registry_integration.sh
