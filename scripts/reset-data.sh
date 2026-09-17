#!/usr/bin/env bash
# reset-data.sh — Borrado completo de datos de sesión de Sity.
#
# Úsalo antes de una ronda de auditoría, QA o test de integración cuando
# quieras partir de una BD limpia sin tocar el schema ni el usuario id=1.
#
# Qué borra:
#   - Todos los mensajes, sesiones, logros, cognición, social, settings, usage
#   - Archivos de audio TTS (data/audio/)
#   - Logs de aplicación (data/logs/app-*.jsonl, audit-*.jsonl)
#   - Contenido de data/file_backups/
#   - Tokens OAuth (google_token.json, spotify_token.json) si existen
#   - Bases de datos huérfanas (data/sity.db, data/db.sqlite3)
#
# Qué preserva:
#   - Usuario id=1 (Alex) y su contraseña
#   - Schema completo de la BD
#   - personalityalter (configuración de alters)
#   - Código fuente, config/, modelos TTS
#
# Uso:
#   ./scripts/reset-data.sh              # pide confirmación interactiva
#   ./scripts/reset-data.sh --confirm    # ejecuta sin preguntar
#   ./scripts/reset-data.sh --dry-run    # lista qué haría, sin tocar nada

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$REPO_ROOT/data/app.db"
DATE="$(date +%Y-%m-%d)"
BACKUP_DIR="/home/$(whoami)/SITY-RESET-BACKUP-${DATE}"

DRY_RUN=false
CONFIRM=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY_RUN=true  ;;
    --confirm)  CONFIRM=true  ;;
    *) echo "Uso: $0 [--confirm] [--dry-run]"; exit 1 ;;
  esac
done

# ── helpers ────────────────────────────────────────────────────────────────

run() {
  # run <description> <command...>
  local desc="$1"; shift
  if $DRY_RUN; then
    echo "  [dry-run] $desc"
  else
    "$@"
    echo "  -> $desc"
  fi
}

safe_rm() {
  # safe_rm <glob-or-path>  — elimina sin error si no existe
  if $DRY_RUN; then
    echo "  [dry-run] rm -f $1"
  else
    eval "rm -f $1" 2>/dev/null || true
  fi
}

# ── confirmación interactiva ────────────────────────────────────────────────

if ! $DRY_RUN && ! $CONFIRM; then
  echo "Este script borrará TODOS los datos de sesión de Sity (DB + audio + logs)."
  echo "El usuario id=1 y el schema se preservan. Se creará backup en $BACKUP_DIR."
  printf "¿Continuar? [s/N] "
  read -r reply
  [[ "$reply" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }
fi

# ── backup ─────────────────────────────────────────────────────────────────

echo "=== BACKUP ==="
if $DRY_RUN; then
  echo "  [dry-run] mkdir -p $BACKUP_DIR"
  echo "  [dry-run] cp $DB $BACKUP_DIR/app.db.backup-pre-reset-${DATE}"
else
  mkdir -p "$BACKUP_DIR"
  cp "$DB" "$BACKUP_DIR/app.db.backup-pre-reset-${DATE}"
  echo "  -> $BACKUP_DIR/app.db.backup-pre-reset-${DATE}"
fi

# ── borrar datos de BD ──────────────────────────────────────────────────────

echo "=== BORRAR DATOS DB ==="
if $DRY_RUN; then
  echo "  [dry-run] DELETE de 45 tablas en $DB (preserva user id=1 y personalityalter)"
else
  sqlite3 "$DB" <<'SQL'
PRAGMA foreign_keys = OFF;

DELETE FROM chatmessage;
DELETE FROM chatsession;
DELETE FROM aiusage;
DELETE FROM dailymessageusage;
DELETE FROM dailyttsusage;

DELETE FROM autobiographicalnarrative;
DELETE FROM beliefattribution;
DELETE FROM episode;
DELETE FROM expectation;
DELETE FROM goal;
DELETE FROM goalmilestone;
DELETE FROM initiativeevallog;
DELETE FROM memoryfragment;
DELETE FROM mentalstate;
DELETE FROM newsitem;
DELETE FROM notificationlog;
DELETE FROM openloop;
DELETE FROM pendingaction;
DELETE FROM proceduralobservation;
DELETE FROM proceduralpattern;
DELETE FROM reflectionlog;
DELETE FROM relationshipsnapshot;
DELETE FROM scheduledtask;
DELETE FROM selfbelief;
DELETE FROM selfmodel;
DELETE FROM semanticfact;

DELETE FROM opinionsnapshot;
DELETE FROM socialprofile;
DELETE FROM socialreflection;

DELETE FROM fileartifact;
DELETE FROM setting;
DELETE FROM sharedconversation;
DELETE FROM temporaryasset;
DELETE FROM userachievement;
DELETE FROM userintegration;
DELETE FROM pushsubscription;

DELETE FROM sityvalues;
DELETE FROM bugreport;

INSERT INTO chatmessage_fts(chatmessage_fts) VALUES('rebuild');

PRAGMA foreign_keys = ON;
SQL
  echo "  -> DB limpia, FTS5 reconstruido"
fi

# ── archivos ────────────────────────────────────────────────────────────────

echo "=== AUDIO TTS ==="
safe_rm "$REPO_ROOT/data/audio/*.mp3"
safe_rm "$REPO_ROOT/data/audio/*.wav"
safe_rm "$REPO_ROOT/data/audio/*.ogg"
echo "  -> data/audio/ limpio"

echo "=== LOGS ==="
safe_rm "$REPO_ROOT/data/logs/app-*.jsonl"
safe_rm "$REPO_ROOT/data/logs/audit-*.jsonl"
echo "  -> data/logs/ limpio"

echo "=== FILE BACKUPS ==="
safe_rm "$REPO_ROOT/data/file_backups/*"
echo "  -> data/file_backups/ limpio"

echo "=== TOKENS OAuth ==="
safe_rm "$REPO_ROOT/config/google_token.json"
safe_rm "$REPO_ROOT/config/spotify_token.json"
safe_rm "$REPO_ROOT/google_token.json"
safe_rm "$REPO_ROOT/spotify_token.json"
echo "  -> tokens OAuth eliminados (si existían)"

echo "=== ORPHAN DBs ==="
safe_rm "$REPO_ROOT/data/sity.db"
safe_rm "$REPO_ROOT/data/db.sqlite3"
echo "  -> bases de datos huérfanas eliminadas (si existían)"

# ── verificación ────────────────────────────────────────────────────────────

echo "=== VERIFICACIÓN ==="
if $DRY_RUN; then
  echo "  [dry-run] SELECT counts de tablas principales"
else
  sqlite3 "$DB" "
SELECT 'chatmessage',     COUNT(*) FROM chatmessage      UNION ALL
SELECT 'userachievement', COUNT(*) FROM userachievement  UNION ALL
SELECT 'aiusage',         COUNT(*) FROM aiusage          UNION ALL
SELECT 'episode',         COUNT(*) FROM episode          UNION ALL
SELECT 'mentalstate',     COUNT(*) FROM mentalstate      UNION ALL
SELECT 'setting',         COUNT(*) FROM setting          UNION ALL
SELECT 'semanticfact',    COUNT(*) FROM semanticfact     UNION ALL
SELECT 'sityvalues',      COUNT(*) FROM sityvalues       UNION ALL
SELECT 'user_preserved',  COUNT(*) FROM user WHERE id=1;
"
fi

echo "=== LISTO ==="
