#!/usr/bin/env bash
# deploy.sh — actualiza producción tras cambios en mobile/ o backend/.
# Uso: ./deploy.sh
# Requiere: node/npm en PATH, sudo NOPASSWD para systemctl restart sity-backend.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[32m[deploy]\033[0m %s\n' "$*"; }
skip() { printf '\033[33m[deploy]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[deploy] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. Git pull ───────────────────────────────────────────────────────────────
# Guarda hashes ANTES del pull para detectar cambios en archivos críticos.
#
# Por qué persona_system.md y persona_engine.py requieren restart inmediato:
#   _load_persona_template() usa @functools.cache — la primera llamada lee el
#   archivo del disco y guarda el texto en memoria para siempre. Si el archivo
#   cambia pero el proceso no se reinicia, el cache contiene el template viejo
#   (o nuevo), que puede no ser consistente con el formato_map del bytecode en
#   memoria. Bug confirmado 2026-09-22: template con {system_git_block} cacheado
#   por proceso con bytecode anterior → KeyError silencioso en cada mensaje.
PERSONA_MD="backend/app/prompts/persona_system.md"
PERSONA_PY="backend/app/core/persona_engine.py"
ADMIN_SEEDER="backend/app/auth/admin_seeder.py"
DEPLOY_SH="deploy.sh"
hash_before_md=$(git -C "$REPO" rev-parse HEAD:"$PERSONA_MD" 2>/dev/null || echo "absent")
hash_before_py=$(git -C "$REPO" rev-parse HEAD:"$PERSONA_PY" 2>/dev/null || echo "absent")
hash_before_seeder=$(git -C "$REPO" rev-parse HEAD:"$ADMIN_SEEDER" 2>/dev/null || echo "absent")
hash_before_deploy=$(git -C "$REPO" rev-parse HEAD:"$DEPLOY_SH" 2>/dev/null || echo "absent")

log "Actualizando código (git pull)…"
git -C "$REPO" pull --ff-only

hash_after_md=$(git -C "$REPO" rev-parse HEAD:"$PERSONA_MD" 2>/dev/null || echo "absent")
hash_after_py=$(git -C "$REPO" rev-parse HEAD:"$PERSONA_PY" 2>/dev/null || echo "absent")
hash_after_seeder=$(git -C "$REPO" rev-parse HEAD:"$ADMIN_SEEDER" 2>/dev/null || echo "absent")
hash_after_deploy=$(git -C "$REPO" rev-parse HEAD:"$DEPLOY_SH" 2>/dev/null || echo "absent")

persona_changed=false
if [[ "$hash_before_md" != "$hash_after_md" ]]; then
    log "  → $PERSONA_MD cambió — restart requerido (template cacheado en memoria)"
    persona_changed=true
fi
if [[ "$hash_before_py" != "$hash_after_py" ]]; then
    log "  → $PERSONA_PY cambió — restart requerido (bytecode + format_map)"
    persona_changed=true
fi
if [[ "$hash_before_seeder" != "$hash_after_seeder" ]]; then
    log "  → $ADMIN_SEEDER cambió — restart requerido (seed_admin() corre en arranque)"
    persona_changed=true
fi
if [[ "$hash_before_deploy" != "$hash_after_deploy" ]]; then
    log "  → $DEPLOY_SH cambió — ejecuta el nuevo script en el próximo deploy"
fi

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
# Siempre reinicia: garantiza que cualquier cambio en .py o en archivos con
# cache en memoria (templates, configs) quede activo sin ambigüedad.
if $persona_changed; then
    log "Reiniciando sity-backend (persona template o engine cambiaron)…"
else
    log "Reiniciando sity-backend…"
fi
sudo systemctl restart sity-backend
log "Backend OK."

log "Deploy completado."
