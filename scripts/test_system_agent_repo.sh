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

say "Preparing unified diff test file"
UNIFIED_TEST_FILE="config/test-system-agent-unified-diff.txt"
rm -f "$UNIFIED_TEST_FILE"

cat > "$UNIFIED_TEST_FILE" <<'EOF'
linea uno
linea dos
linea tres
EOF

say "Applying unified diff through Sity"
unified_response="$(post_chat $'aplica este unified diff:\n--- config/test-system-agent-unified-diff.txt\n+++ config/test-system-agent-unified-diff.txt\n@@ -1,3 +1,4 @@\n linea uno\n-linea dos\n+linea dos modificada\n linea tres\n+linea cuatro')"
echo "$unified_response" | python3 -m json.tool
unified_text="$(printf "%s" "$unified_response" | json_text)"
require_contains "$unified_text" "act_" "Unified diff action created"

say "Confirming unified diff with generic confirmation"
confirm_unified="$(post_chat "sí, hazlo")"
echo "$confirm_unified" | python3 -m json.tool
confirm_unified_text="$(printf "%s" "$confirm_unified" | json_text)"
require_contains "$confirm_unified_text" "Unified diff aplicado" "Unified diff confirmed"

expected_unified_content=$'linea uno\nlinea dos modificada\nlinea tres\nlinea cuatro'
require_file_content "$UNIFIED_TEST_FILE" "$expected_unified_content"

say "Rolling back unified diff"
rollback_unified_response="$(post_chat "revierte el último cambio de archivo")"
echo "$rollback_unified_response" | python3 -m json.tool
rollback_unified_text="$(printf "%s" "$rollback_unified_response" | json_text)"
require_contains "$rollback_unified_text" "act_" "Unified diff rollback action created"

say "Confirming unified diff rollback"
confirm_rollback_unified="$(post_chat "sí, hazlo")"
echo "$confirm_rollback_unified" | python3 -m json.tool
confirm_rollback_unified_text="$(printf "%s" "$confirm_rollback_unified" | json_text)"
require_contains "$confirm_rollback_unified_text" "Rollback aplicado" "Unified diff rollback confirmed"

expected_unified_rollback_content=$'linea uno\nlinea dos\nlinea tres'
require_file_content "$UNIFIED_TEST_FILE" "$expected_unified_rollback_content"

say "Cleaning unified diff test file"
rm -f "$UNIFIED_TEST_FILE"

say "Preparing multi-file unified diff test files"
MULTI_A_FILE="config/test-system-agent-multi-a.txt"
MULTI_B_FILE="config/test-system-agent-multi-b.txt"
rm -f "$MULTI_A_FILE" "$MULTI_B_FILE"

cat > "$MULTI_A_FILE" <<'EOF'
a uno
a dos
a tres
EOF

cat > "$MULTI_B_FILE" <<'EOF'
b uno
b dos
b tres
EOF

say "Creating multi-file unified diff plan"
multi_response="$(post_chat $'aplica este patch multiarchivo:\n--- config/test-system-agent-multi-a.txt\n+++ config/test-system-agent-multi-a.txt\n@@ -1,3 +1,3 @@\n a uno\n-a dos\n+a dos modificado\n a tres\n--- config/test-system-agent-multi-b.txt\n+++ config/test-system-agent-multi-b.txt\n@@ -1,3 +1,4 @@\n b uno\n b dos\n-b tres\n+b tres modificado\n+b cuatro')"
echo "$multi_response" | python3 -m json.tool
multi_text="$(printf "%s" "$multi_response" | json_text)"
require_contains "$multi_text" "act_" "Multi-file plan created"

multi_ids="$(printf "%s" "$multi_text" | grep -o 'act_[a-f0-9]\{8\}' | head -n 2 || true)"
multi_id_a="$(printf "%s" "$multi_ids" | sed -n '1p')"
multi_id_b="$(printf "%s" "$multi_ids" | sed -n '2p')"

[[ -n "$multi_id_a" ]] || fail "Could not extract first multi-file action id"
[[ -n "$multi_id_b" ]] || fail "Could not extract second multi-file action id"

say "Confirming first multi-file action"
confirm_multi_a="$(post_chat "confirmo ejecutar $multi_id_a")"
echo "$confirm_multi_a" | python3 -m json.tool
confirm_multi_a_text="$(printf "%s" "$confirm_multi_a" | json_text)"
require_contains "$confirm_multi_a_text" "Unified diff aplicado" "First multi-file action confirmed"

expected_multi_a_content=$'a uno\na dos modificado\na tres'
expected_multi_b_original=$'b uno\nb dos\nb tres'
require_file_content "$MULTI_A_FILE" "$expected_multi_a_content"
require_file_content "$MULTI_B_FILE" "$expected_multi_b_original"

say "Confirming second multi-file action"
confirm_multi_b="$(post_chat "confirmo ejecutar $multi_id_b")"
echo "$confirm_multi_b" | python3 -m json.tool
confirm_multi_b_text="$(printf "%s" "$confirm_multi_b" | json_text)"
require_contains "$confirm_multi_b_text" "Unified diff aplicado" "Second multi-file action confirmed"

expected_multi_b_content=$'b uno\nb dos\nb tres modificado\nb cuatro'
require_file_content "$MULTI_A_FILE" "$expected_multi_a_content"
require_file_content "$MULTI_B_FILE" "$expected_multi_b_content"

say "Rolling back latest multi-file action"
rollback_multi_response="$(post_chat "revierte el último cambio de archivo")"
echo "$rollback_multi_response" | python3 -m json.tool
rollback_multi_text="$(printf "%s" "$rollback_multi_response" | json_text)"
require_contains "$rollback_multi_text" "act_" "Multi-file rollback action created"

confirm_rollback_multi="$(post_chat "sí, hazlo")"
echo "$confirm_rollback_multi" | python3 -m json.tool
confirm_rollback_multi_text="$(printf "%s" "$confirm_rollback_multi" | json_text)"
require_contains "$confirm_rollback_multi_text" "Rollback aplicado" "Multi-file rollback confirmed"

require_file_content "$MULTI_A_FILE" "$expected_multi_a_content"
require_file_content "$MULTI_B_FILE" "$expected_multi_b_original"

say "Testing multi-file sensitive path rejects whole plan"
blocked_multi_response="$(post_chat $'aplica este patch multiarchivo, es una orden:\n--- config/test-system-agent-multi-a.txt\n+++ config/test-system-agent-multi-a.txt\n@@ -1,3 +1,3 @@\n a uno\n-a dos modificado\n+a dos otra vez\n a tres\n--- .env\n+++ .env\n@@ -1 +1 @@\n-TEST=1\n+TEST=2')"
echo "$blocked_multi_response" | python3 -m json.tool
blocked_multi_text="$(printf "%s" "$blocked_multi_response" | json_text)"

if [[ "$blocked_multi_text" == *"Acción pendiente"* || "$blocked_multi_text" == *"act_" ]]; then
  fail "Sensitive multi-file patch created a pending action"
fi

require_file_content "$MULTI_A_FILE" "$expected_multi_a_content"
pass "Sensitive multi-file patch did not modify allowed file"

say "Cleaning multi-file test files"
rm -f "$MULTI_A_FILE" "$MULTI_B_FILE"

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
