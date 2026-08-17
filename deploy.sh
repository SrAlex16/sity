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
# Build siempre — la detección condicional por mtime falló silenciosamente varias
# veces (deploy.sh no era llamado; cuando sí se llama, mtime puede no reflejar
# cambios reales). El coste de un build extra (~35s) es menor que un diagnóstico
# de bundle stale. Si el coste de build se vuelve inaceptable, usar
# .last-build-commit como marca en vez de mtime.
log "Reconstruyendo frontend…"
(cd "$REPO/mobile" && npm run build) || die "npm run build falló — deploy abortado."
NEW_BUNDLE=$(ls "$REPO/mobile/dist/assets"/index-*.js 2>/dev/null | head -1 || true)
log "Frontend OK  →  $(basename "$NEW_BUNDLE")"

# ── 2. Backend ────────────────────────────────────────────────────────────────
log "Reiniciando sity-backend…"
sudo systemctl restart sity-backend
log "Backend OK."

log "Deploy completado."
