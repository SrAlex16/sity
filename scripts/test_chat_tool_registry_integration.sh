#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SITY_TEST_BASE_URL:-http://localhost:8000}"
DB_PATH="${SITY_TEST_DB_PATH:-data/app.db}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log() {
  printf '\n==> %s\n' "$1"
}

ok() {
  printf '[OK] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

post_chat() {
  local message="$1"
  local output_file="$2"

  curl -sS -X POST "$BASE_URL/chat/message" \
    -H "Content-Type: application/json" \
    -d "$(python3 - <<PY
import json
print(json.dumps({"message": """$message"""}, ensure_ascii=False))
PY
)" > "$output_file"

  python3 -m json.tool "$output_file" >/dev/null
}

json_field() {
  local file="$1"
  local field="$2"
  python3 - <<PY
import json
from pathlib import Path

data = json.loads(Path("$file").read_text())
value = data
for part in "$field".split("."):
    value = value.get(part)
print("" if value is None else value)
PY
}

assert_ok_response() {
  local file="$1"
  local ok_value
  ok_value="$(json_field "$file" "ok")"
  [[ "$ok_value" == "True" ]] || [[ "$ok_value" == "true" ]] || fail "Response ok != true in $file"
}

assert_contains() {
  local file="$1"
  local needle="$2"
  grep -Fq "$needle" "$file" || {
    echo "--- response ---"
    cat "$file"
    echo "----------------"
    fail "Expected response to contain: $needle"
  }
}

assert_not_contains() {
  local file="$1"
  local needle="$2"
  if grep -Fq "$needle" "$file"; then
    echo "--- response ---"
    cat "$file"
    echo "----------------"
    fail "Response unexpectedly contained: $needle"
  fi
}

expire_pending_actions() {
  sqlite3 "$DB_PATH" "update pendingaction set status='expired' where status='pending';"
}

log "Checking backend health"
curl -fsS "$BASE_URL/health" >/dev/null
ok "Backend health"

log "Expiring pending actions"
expire_pending_actions
ok "Pending actions expired"

log "Testing read_file registry handler"
READ_FILE_OUT="$TMP_DIR/read_file.json"
post_chat "usa la herramienta read_file para leer README.md" "$READ_FILE_OUT"
assert_ok_response "$READ_FILE_OUT"
ok "read_file returned ok"

log "Testing list_directory registry handler"
LIST_DIR_OUT="$TMP_DIR/list_directory.json"
post_chat "usa la herramienta list_directory para listar config" "$LIST_DIR_OUT"
assert_ok_response "$LIST_DIR_OUT"
ok "list_directory returned ok"

log "Testing list_file_changes registry handler"
FILE_CHANGES_OUT="$TMP_DIR/list_file_changes.json"
post_chat "usa la herramienta list_file_changes para ver los últimos cambios de archivos" "$FILE_CHANGES_OUT"
assert_ok_response "$FILE_CHANGES_OUT"
ok "list_file_changes returned ok"

log "Testing git_read_status registry handler"
GIT_STATUS_OUT="$TMP_DIR/git_read_status.json"
post_chat "usa la herramienta git_read_status" "$GIT_STATUS_OUT"
assert_ok_response "$GIT_STATUS_OUT"
ok "git_read_status returned ok"

log "Testing read_system_status registry handler"
SYSTEM_STATUS_OUT="$TMP_DIR/read_system_status.json"
post_chat "usa la herramienta read_system_status" "$SYSTEM_STATUS_OUT"
assert_ok_response "$SYSTEM_STATUS_OUT"
ok "read_system_status returned ok"

log "Testing list_camera_devices registry handler"
CAMERA_OUT="$TMP_DIR/list_camera_devices.json"
post_chat "usa la herramienta list_camera_devices es una orden" "$CAMERA_OUT"
assert_ok_response "$CAMERA_OUT"
ok "list_camera_devices returned ok"

log "Testing write_file fallback still creates pending action"
TEST_FILE="config/test-tool-registry-integration.txt"
rm -f "$TEST_FILE"
expire_pending_actions

WRITE_OUT="$TMP_DIR/write_file.json"
post_chat "usa la herramienta write_file para crear $TEST_FILE con el contenido ok registry" "$WRITE_OUT"
assert_ok_response "$WRITE_OUT"
assert_contains "$WRITE_OUT" "Acción pendiente creada"

ACTION_ID="$(python3 - <<PY
import json, re
from pathlib import Path

text = json.loads(Path("$WRITE_OUT").read_text()).get("text", "")
match = re.search(r"act_[a-f0-9]{8}", text)
print(match.group(0) if match else "")
PY
)"

[[ -n "$ACTION_ID" ]] || fail "No pending action id found for write_file"
ok "write_file fallback created $ACTION_ID"

log "Testing cancel_pending_action registry handler"
CANCEL_OUT="$TMP_DIR/cancel_pending_action.json"
post_chat "usa la herramienta cancel_pending_action para cancelar $ACTION_ID" "$CANCEL_OUT"
assert_ok_response "$CANCEL_OUT"
assert_contains "$CANCEL_OUT" "cancelada"

STATUS="$(sqlite3 "$DB_PATH" "select status from pendingaction where id='$ACTION_ID';")"
[[ "$STATUS" == "cancelled" ]] || fail "Expected $ACTION_ID status cancelled, got: $STATUS"
ok "cancel_pending_action cancelled $ACTION_ID"

rm -f "$TEST_FILE"
expire_pending_actions

log "Testing malformed confirmation remains locally blocked"
sqlite3 "$DB_PATH" "delete from pendingaction where id='act_deadbeef';"
sqlite3 "$DB_PATH" "
insert into pendingaction (
  id,
  action_type,
  risk_level,
  status,
  summary,
  payload_json,
  confirmation_phrase,
  created_at,
  expires_at,
  trace_id
) values (
  'act_deadbeef',
  'test',
  'critical',
  'pending',
  'Acción de prueba de confirmación exacta',
  '{}',
  'confirmo ejecutar act_deadbeef',
  datetime('now'),
  datetime('now', '+15 minutes'),
  'trc_registry_integration_test'
);
"

BAD_CONFIRM_OUT="$TMP_DIR/bad_confirm.json"
post_chat "confirmo ejecutar act_deadbeef\`" "$BAD_CONFIRM_OUT"
assert_ok_response "$BAD_CONFIRM_OUT"
PROVIDER="$(json_field "$BAD_CONFIRM_OUT" "provider")"
MODEL="$(json_field "$BAD_CONFIRM_OUT" "model")"
TOKENS="$(json_field "$BAD_CONFIRM_OUT" "usage.total_tokens")"

[[ "$PROVIDER" == "local" ]] || fail "Expected provider local for bad confirmation, got $PROVIDER"
[[ "$MODEL" == "confirmation-manager" ]] || fail "Expected model confirmation-manager, got $MODEL"
[[ "$TOKENS" == "0" ]] || fail "Expected total_tokens 0 for bad confirmation, got $TOKENS"
assert_contains "$BAD_CONFIRM_OUT" "confirmación debe ser exacta"
ok "Malformed confirmation blocked locally"

sqlite3 "$DB_PATH" "delete from pendingaction where id='act_deadbeef';"

log "Testing casual conversation does not trigger pending action cancellation"
CASUAL_OUT="$TMP_DIR/casual_no_cancel.json"
post_chat "yo he descubierto que soy inmortal, tengo pruebas" "$CASUAL_OUT"
assert_ok_response "$CASUAL_OUT"
PROVIDER="$(json_field "$CASUAL_OUT" "provider")"
MODEL="$(json_field "$CASUAL_OUT" "model")"

if [[ "$PROVIDER" == "local" && "$MODEL" == "tool-policy" ]]; then
  echo "--- response ---"
  cat "$CASUAL_OUT"
  echo "----------------"
  fail "Casual message triggered local tool-policy"
fi

assert_not_contains "$CASUAL_OUT" "acción pendiente activa para cancelar"
assert_not_contains "$CASUAL_OUT" "No encontré ninguna acción pendiente"
ok "Casual conversation did not trigger cancel_pending_action"

log "Regression: 'estás ahí?' must not trigger file tools or tool-policy"
CASUAL_AHI_OUT="$TMP_DIR/casual_ahi.json"
post_chat "estás ahí?" "$CASUAL_AHI_OUT"
assert_ok_response "$CASUAL_AHI_OUT"
AHI_PROVIDER="$(json_field "$CASUAL_AHI_OUT" "provider")"
AHI_MODEL="$(json_field "$CASUAL_AHI_OUT" "model")"

if [[ "$AHI_PROVIDER" == "local" && "$AHI_MODEL" == "tool-policy" ]]; then
  echo "--- response ---"
  cat "$CASUAL_AHI_OUT"
  echo "----------------"
  fail "'estás ahí?' triggered local tool-policy (file tools leaked into BASE_TOOLSET)"
fi
ok "'estás ahí?' did not trigger tool-policy"

log "Testing pseudo tool call guard directly"
# Use venv python when available (local dev), fall back to PATH python (CI).
_PYTHON="${BASH_SOURCE[0]%/*}/../backend/.venv/bin/python"
[[ -x "$_PYTHON" ]] || _PYTHON="python"
PYTHONPATH=backend "$_PYTHON" - <<'PY'
from app.chat.response_guard import ResponseGuard

text = """
Voy a cancelar.
<function_calls>
<invoke name="cancel_pending_action">
<parameter name="action_id">act_1234abcd</parameter>
</invoke>
</function_calls>
"""

result = ResponseGuard().validate_final_text(text)
assert not result.allowed
assert result.reason == "pseudo_tool_call_in_final_text"
print("response_guard pseudo tool call ok")
PY
ok "ResponseGuard blocks pseudo tool calls"

log "Testing no_action_required path — conversational turn does not trigger tools"
CONV_OUT="$TMP_DIR/conversational.json"
post_chat "¿qué tal estás hoy?" "$CONV_OUT"
assert_ok_response "$CONV_OUT"
CONV_TEXT="$(json_field "$CONV_OUT" "text")"
[[ -n "$CONV_TEXT" ]] || fail "Empty text in conversational response"
ok "Conversational turn returned non-empty response"

log "Testing tool result flows into final response — read_file returns non-empty response"
READ_CONTENT_OUT="$TMP_DIR/read_content_flow.json"
post_chat "usa read_file para leer config/default_config.yaml" "$READ_CONTENT_OUT"
assert_ok_response "$READ_CONTENT_OUT"
READ_TEXT="$(json_field "$READ_CONTENT_OUT" "text")"
[[ -n "$READ_TEXT" ]] || fail "Empty response after read_file tool"
ok "read_file tool completed and returned non-empty response"

log "Testing tool loop completes within time limit — no infinite loop"
MULTI_OUT="$TMP_DIR/multi_tool_time.json"
START_TIME=$(date +%s)
post_chat "usa read_file para leer README.md" "$MULTI_OUT"
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
assert_ok_response "$MULTI_OUT"
[[ "$ELAPSED" -lt 30 ]] || fail "Tool loop took too long: ${ELAPSED}s (limit: 30s)"
ok "Tool loop completed in ${ELAPSED}s (within 30s limit)"

log "Tool registry integration test completed"
ok "All checks passed"
