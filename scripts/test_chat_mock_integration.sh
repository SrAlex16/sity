#!/usr/bin/env bash
# Run the chat tool registry integration test against a local mock backend.
#
# Does NOT modify the system service. Launches a temporary uvicorn on port 8010
# with SITY_AI_PROVIDER=mock and SITY_DAILY_TOKEN_HARD_CAP=false, runs the
# integration test, then stops the backend.
#
# Usage:
#   ./scripts/test_chat_mock_integration.sh
#
# Prerequisites: backend .venv must exist (run `pip install -e .` inside backend/).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$ROOT/backend"
MOCK_PORT=8010
MOCK_URL="http://127.0.0.1:$MOCK_PORT"
UVICORN_LOG="$(mktemp /tmp/sity-mock-backend.XXXXXX.log)"

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
  .venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port "$MOCK_PORT" \
    --no-access-log \
    > "$UVICORN_LOG" 2>&1 &

MOCK_PID=$!

# Wait for backend to be ready (up to 10s)
for i in $(seq 1 10); do
  if curl -fsS "$MOCK_URL/health" >/dev/null 2>&1; then
    printf '[OK] Mock backend ready (%.0fs)\n' "$i"
    break
  fi
  sleep 1
  if [[ "$i" -eq 10 ]]; then
    echo '[FAIL] Mock backend did not start in 10s'
    cat "$UVICORN_LOG"
    exit 1
  fi
done

printf '==> Running integration test suite\n\n'
cd "$ROOT"
SITY_TEST_BASE_URL="$MOCK_URL" ./scripts/test_chat_tool_registry_integration.sh
