#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SITY_TEST_BASE_URL:-http://localhost:8000}"
DB_PATH="${SITY_TEST_DB_PATH:-data/app.db}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log()  { printf '\n==> %s\n' "$1"; }
ok()   { printf '[OK] %s\n' "$1"; }
skip() { printf '[SKIP] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

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

assert_ok_response() {
  local file="$1"
  local ok_value
  ok_value="$(python3 - <<PY
import json
from pathlib import Path
print(json.loads(Path("$file").read_text()).get("ok", ""))
PY
)"
  [[ "$ok_value" == "True" ]] || [[ "$ok_value" == "true" ]] || {
    echo "--- response ---"
    cat "$file"
    echo "----------------"
    fail "Response ok != true in $file"
  }
}

json_str() {
  local file="$1"
  local field="$2"
  python3 - <<PY
import json
from pathlib import Path
data = json.loads(Path("$file").read_text())
value = data
for part in "$field".split("."):
    value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
PY
}

# Returns first artifact's field (artifacts[0].type, etc.)
artifact_field() {
  local file="$1"
  local field="$2"
  python3 - <<PY
import json
from pathlib import Path
data = json.loads(Path("$file").read_text())
artifacts = data.get("artifacts") or []
art = artifacts[0] if artifacts else {}
print(art.get("$field", ""))
PY
}

expire_pending_actions() {
  sqlite3 "$DB_PATH" "update pendingaction set status='expired' where status='pending';"
}

clear_recent_chat_history() {
  sqlite3 "$DB_PATH" "delete from chatmessage where created_at >= datetime('now', '-2 hours');"
}

# ── Health ────────────────────────────────────────────────────────────────────

log "Checking backend health"
curl -fsS "$BASE_URL/health" >/dev/null
ok "Backend health"

log "Clearing recent chat history to avoid history contamination"
expire_pending_actions
clear_recent_chat_history
ok "State reset"

# ── list_camera_devices (already in registry) ─────────────────────────────────

log "Testing list_camera_devices"
CAM_DEV_OUT="$TMP_DIR/list_camera_devices.json"
post_chat "usa la herramienta list_camera_devices es una orden" "$CAM_DEV_OUT"
assert_ok_response "$CAM_DEV_OUT"
ok "list_camera_devices returned ok"

# ── list_audio_devices (already in registry) ──────────────────────────────────

log "Testing list_audio_devices"
AUD_DEV_OUT="$TMP_DIR/list_audio_devices.json"
post_chat "usa la herramienta list_audio_devices es una orden" "$AUD_DEV_OUT"
assert_ok_response "$AUD_DEV_OUT"
ok "list_audio_devices returned ok"

# ── get_capture_storage_summary (already in registry) ────────────────────────

log "Testing get_capture_storage_summary"
STORAGE_OUT="$TMP_DIR/storage_summary.json"
post_chat "usa la herramienta get_capture_storage_summary es una orden" "$STORAGE_OUT"
assert_ok_response "$STORAGE_OUT"
ok "get_capture_storage_summary returned ok"

# ── capture_camera_snapshot ───────────────────────────────────────────────────

log "Testing capture_camera_snapshot"
SNAP_BEFORE="$(find captures/camera -type f -name '*.jpg' 2>/dev/null | wc -l || echo 0)"
SNAP_OUT="$TMP_DIR/capture_camera_snapshot.json"
post_chat "usa la herramienta capture_camera_snapshot para sacar una captura de prueba es una orden" "$SNAP_OUT"
assert_ok_response "$SNAP_OUT"

SNAP_MODEL="$(json_str "$SNAP_OUT" "model")"
if [[ "$SNAP_MODEL" == "micro_reaction" ]]; then
  SNAP_AFTER="$(find captures/camera -type f -name '*.jpg' 2>/dev/null | wc -l || echo 0)"
  [[ "$SNAP_AFTER" -gt "$SNAP_BEFORE" ]] || fail "No new .jpg file in captures/camera after snapshot"
  ok "capture_camera_snapshot created file in captures/camera"

  ARTIFACT_TYPE="$(artifact_field "$SNAP_OUT" "type")"
  [[ "$ARTIFACT_TYPE" == "image" ]] || fail "Expected artifacts[0].type=image, got: $ARTIFACT_TYPE"
  ok "capture_camera_snapshot artifact type=image"

  ARTIFACT_URL="$(artifact_field "$SNAP_OUT" "url")"
  [[ "$ARTIFACT_URL" == /captures/camera/* ]] || fail "Unexpected artifact url: $ARTIFACT_URL"
  ok "capture_camera_snapshot artifact url prefix ok"
else
  echo "--- response ---"
  cat "$SNAP_OUT"
  echo "----------------"
  fail "Expected model=micro_reaction for successful capture, got: $SNAP_MODEL"
fi

# ── record_audio_sample (tolerant — device may not be available) ──────────────

log "Testing record_audio_sample (tolerant)"
AUDIO_BEFORE="$(find captures/audio -type f -name '*.wav' 2>/dev/null | wc -l || echo 0)"
AUDIO_OUT="$TMP_DIR/record_audio_sample.json"
post_chat "usa la herramienta record_audio_sample para grabar 1 segundo de prueba es una orden" "$AUDIO_OUT"
assert_ok_response "$AUDIO_OUT"

AUDIO_MODEL="$(json_str "$AUDIO_OUT" "model")"
if [[ "$AUDIO_MODEL" == "micro_reaction" ]]; then
  AUDIO_AFTER="$(find captures/audio -type f -name '*.wav' 2>/dev/null | wc -l || echo 0)"
  [[ "$AUDIO_AFTER" -gt "$AUDIO_BEFORE" ]] || fail "No new .wav file in captures/audio after recording"
  ok "record_audio_sample created file in captures/audio"

  AUDIO_ARTIFACT_TYPE="$(artifact_field "$AUDIO_OUT" "type")"
  [[ "$AUDIO_ARTIFACT_TYPE" == "audio" ]] || fail "Expected artifacts[0].type=audio, got: $AUDIO_ARTIFACT_TYPE"
  ok "record_audio_sample artifact type=audio"
else
  skip "record_audio_sample did not return micro_reaction (model=$AUDIO_MODEL) — device may be unavailable"
fi

# ── write_file regression: pending action still created after sense ops ────────

log "Testing write_file fallback still works after sense operations"
expire_pending_actions
WRITE_OUT="$TMP_DIR/write_file_after_sense.json"
TEST_FILE="config/test-sense-integration.txt"
rm -f "$TEST_FILE"
post_chat "usa la herramienta write_file para crear $TEST_FILE con el contenido ok sense regression" "$WRITE_OUT"
assert_ok_response "$WRITE_OUT"

grep -Fq "Acción pendiente creada" "$WRITE_OUT" || {
  echo "--- response ---"
  cat "$WRITE_OUT"
  echo "----------------"
  fail "write_file did not create pending action after sense operations"
}
ok "write_file fallback still creates pending action"

sqlite3 "$DB_PATH" "update pendingaction set status='expired' where status='pending';"
rm -f "$TEST_FILE"

# ─────────────────────────────────────────────────────────────────────────────

log "Sense tools integration test completed"
ok "All checks passed"
