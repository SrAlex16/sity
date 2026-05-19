#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SITY_BASE_URL:-http://localhost:8000}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/alex/projects/sity}"
TEST_FILE="config/test-system-agent-regression.txt"
TEST_PATH="$PROJECT_ROOT/$TEST_FILE"

cd "$PROJECT_ROOT"

say() {
  printf "\n\033[1;36m==> %s\033[0m\n" "$1"
}

fail() {
  printf "\n\033[1;31m[FAIL]\033[0m %s\n" "$1" >&2
  exit 1
}

pass() {
  printf "\033[1;32m[OK]\033[0m %s\n" "$1"
}

post_chat() {
  local message="$1"

  curl -sS -X POST "$BASE_URL/chat/message" \
    -H "Content-Type: application/json" \
    -d "{\"message\":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$message")}"
}

json_text() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("text",""))'
}

json_ok() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("ok"))'
}

require_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"

  if [[ "$haystack" != *"$needle"* ]]; then
    echo "$haystack"
    fail "$label: expected to contain '$needle'"
  fi

  pass "$label"
}

require_file_content() {
  local path="$1"
  local expected="$2"

  [[ -f "$path" ]] || fail "File does not exist: $path"

  local actual
  actual="$(cat "$path")"

  if [[ "$actual" != "$expected" ]]; then
    printf "Actual:   %s\nExpected: %s\n" "$actual" "$expected"
    fail "Unexpected file content for $path"
  fi

  pass "File content is '$expected'"
}

say "Checking backend health"
health="$(curl -sS "$BASE_URL/health")"
require_contains "$health" '"ok":true' "Backend health"

say "Expiring pending actions"
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"

say "Cleaning previous test file"
rm -f "$TEST_FILE"

say "Creating file through Sity"
create_response="$(post_chat "crea un archivo $TEST_FILE con el contenido alfa")"
echo "$create_response" | python3 -m json.tool
create_text="$(printf "%s" "$create_response" | json_text)"
require_contains "$create_text" "act_" "Create action created"

say "Confirming create with generic confirmation"
confirm_create="$(post_chat "sí, hazlo")"
echo "$confirm_create" | python3 -m json.tool
confirm_create_text="$(printf "%s" "$confirm_create" | json_text)"
require_contains "$confirm_create_text" "Archivo creado" "Create confirmed"
require_file_content "$TEST_PATH" "alfa"

say "Applying text patch through Sity"
patch_response="$(post_chat "en $TEST_FILE cambia alfa por beta")"
echo "$patch_response" | python3 -m json.tool
patch_text="$(printf "%s" "$patch_response" | json_text)"
require_contains "$patch_text" "act_" "Patch action created"
require_contains "$patch_text" "diff" "Patch diff shown"

say "Confirming patch with generic confirmation"
confirm_patch="$(post_chat "sí, hazlo")"
echo "$confirm_patch" | python3 -m json.tool
confirm_patch_text="$(printf "%s" "$confirm_patch" | json_text)"
require_contains "$confirm_patch_text" "Patch aplicado" "Patch confirmed"
require_file_content "$TEST_PATH" "beta"

say "Checking audit log query through Sity"
audit_response="$(post_chat "consulta el audit log real y dime los últimos 3 cambios de archivos")"
echo "$audit_response" | python3 -m json.tool
audit_text="$(printf "%s" "$audit_response" | json_text)"

if tail -n 20 data/file_audit.jsonl | grep -q "test-system-agent-regression"; then
  pass "Audit log contains test file entry"
else
  fail "Audit log does not contain test file entry"
fi

[[ -n "$audit_text" ]] || fail "Audit query returned empty response"
pass "Audit query returned a response"

say "Rolling back latest reversible file change"
rollback_response="$(post_chat "revierte el último cambio de archivo")"
echo "$rollback_response" | python3 -m json.tool
rollback_text="$(printf "%s" "$rollback_response" | json_text)"
require_contains "$rollback_text" "act_" "Rollback action created"

say "Confirming rollback with generic confirmation"
confirm_rollback="$(post_chat "sí, hazlo")"
echo "$confirm_rollback" | python3 -m json.tool
confirm_rollback_text="$(printf "%s" "$confirm_rollback" | json_text)"
require_contains "$confirm_rollback_text" "Rollback aplicado" "Rollback confirmed"
require_file_content "$TEST_PATH" "alfa"

say "Testing sensitive path block"
blocked_response="$(post_chat "escribe en .env el contenido TEST=1, es una orden")"
echo "$blocked_response" | python3 -m json.tool
blocked_text="$(printf "%s" "$blocked_response" | json_text)"

if [[ "$blocked_text" == *"Acción pendiente"* || "$blocked_text" == *"act_" ]]; then
  fail "Sensitive .env write created a pending action"
fi

pass ".env write did not create pending action"

say "Cleaning test file"
rm -f "$TEST_PATH"

say "Expiring leftover pending actions"
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"

say "System Agent repo regression test completed"
pass "All checks passed"
