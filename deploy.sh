#!/usr/bin/env bash
# deploy.sh — actualiza producción tras cambios en mobile/ o backend/.
# Uso: ./deploy.sh
# Requiere: node/npm en PATH, sudo NOPASSWD para systemctl restart sity-backend.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[32m[deploy]\033[0m %s\n' "$*"; }
skip() { printf '\033[33m[deploy]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[deploy] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 1. Frontend ───────────────────────────────────────────────────────────────
DIST_BUNDLE=$(ls "$REPO/mobile/dist/assets"/index-*.js 2>/dev/null | head -1 || true)
NEEDS_BUILD=false

if [[ -z "$DIST_BUNDLE" ]]; then
  NEEDS_BUILD=true
elif find "$REPO/mobile/src" "$REPO/mobile/public" \
    -newer "$DIST_BUNDLE" -type f -print -quit 2>/dev/null | grep -q .; then
  NEEDS_BUILD=true
fi

if $NEEDS_BUILD; then
  log "Cambios en mobile/ detectados — reconstruyendo frontend…"
  (cd "$REPO/mobile" && npm run build) || die "npm run build falló — deploy abortado."
  NEW_BUNDLE=$(ls "$REPO/mobile/dist/assets"/index-*.js 2>/dev/null | head -1 || true)
  log "Frontend OK  →  $(basename "$NEW_BUNDLE")"
else
  skip "Frontend sin cambios desde el último build — omitiendo."
fi

# ── 2. Backend ────────────────────────────────────────────────────────────────
log "Reiniciando sity-backend…"
sudo systemctl restart sity-backend
log "Backend OK."

log "Deploy completado."
