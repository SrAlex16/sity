# File Management Architecture

## Context

**Paso 1** (2026-09-07): every image or audio file that enters the system is persisted
to disk and registered in the `FileArtifact` inventory table.

**Paso 2** (2026-09-07): multi-turn visual context — uploaded images are now included
in prior_messages when Claude generates responses, so the model can see images from
recent turns. The `FileArtifact.chat_message_id` field is populated and used for this.

**Paso 3** (2026-09-07): frontend file manager — list, delete individually/in bulk,
export as zip. See §Paso 3 below.

**Ampliación en 8 partes** (2026-09-29): storage limits, retention policy, semantic
extraction, push alerts, permanent flag, storage stats endpoint. See §Ampliación below.

## FileArtifact table

```
fileartifact
────────────────────────────────────────────────────────────────────
id                INTEGER PRIMARY KEY
user_id           INTEGER  NULL    — None for guest sessions; indexed
artifact_type     TEXT             — "image" | "audio"
filename          TEXT             — bare filename, e.g. "a1b2.jpg"
rel_path          TEXT             — path relative to PROJECT_ROOT
                                     e.g. "uploads/images/a1b2.jpg"
                                          "captures/camera/snap.jpg"
mime_type         TEXT  NULL
source            TEXT             — "chat_upload" | "camera_capture"
chat_message_id   INTEGER NULL     — id of the ChatMessage that owns this file
                                     (wired in Paso 2; used for image history)
created_at        DATETIME

— Added in Ampliación (2026-09-29) —
file_size_bytes   INTEGER  NOT NULL DEFAULT 0
                                   — populated from len(raw_bytes) on upload or
                                     path.stat().st_size for capture artifacts
is_permanent      INTEGER  NOT NULL DEFAULT 0  (bool)
                                   — True → exempt from auto-deletion
expires_at        DATETIME NULL    — computed as now + retention_days at upload time;
                                     NULL means use the legacy created_at cutoff
semantic_extracted INTEGER NOT NULL DEFAULT 0  (bool)
                                   — True → Haiku has already run image analysis
```

The same `user_id` isolation criterion already applied in `UserAchievement`,
`UserIntegration`, etc. applies here: every query that exposes files to the user
must filter by `user_id`. Guest rows have `user_id=NULL`.

## Two entry points

### 1. Chat upload (`source = "chat_upload"`)

Images arrive as `ChatImageInput(media_type, data)` in `ChatMessageRequest.images`.
The route handler `POST /chat/message` calls `save_uploaded_image()` for each image:

1. Decode base64 → raw bytes
2. Write to `PROJECT_ROOT/uploads/images/<uuid>.{ext}`
3. Insert `FileArtifact` row (chat_message_id still NULL at this point)
4. Collect the FileArtifact IDs and pass them to the background turn worker
5. After the user's `ChatMessage` is saved inside the worker, wire the IDs via
   `wire_uploaded_images_to_message()` (sets `chat_message_id` on each row)
6. On subsequent turns `_load_history()` reads these FileArtifact rows and re-encodes
   the files as base64 to include as image content blocks in `prior_messages`

The `request.images` base64 is **unchanged** for the current turn — the Anthropic API
requires base64 inline; there is no URL-based image input. The file on disk is used
only for the inventory and for re-injecting the image in later turns.

Files are served at `GET /uploads/images/{filename}` (routes_uploads.py).

### 2. Camera / audio capture (`source = "camera_capture"`)

The `capture_camera_snapshot` and `record_audio_sample` tools write files to
`PROJECT_ROOT/captures/camera/` and `PROJECT_ROOT/captures/audio/` respectively.
`capture_artifact_from_path()` wraps the path in a `ChatArtifact` (unchanged).
Registration into `FileArtifact` happens via `register_capture_artifact()` at two
call sites:

- `ChatAIOrchestrator._execute_tool_branch()` — normal tool loop and sensor paths
- `PendingActionRunner.run()` — deferred sense actions confirmed by the user

Both call sites use `self.session` / `ctx.session` (already available), so no new
DB session is created.

## File layout on disk

```
PROJECT_ROOT/
  uploads/
    images/               ← chat-uploaded images
      <uuid>.jpg / .png / .webp / .gif

  captures/
    camera/               ← camera snapshots (existing)
    audio/                ← audio recordings (existing)
```

## Model call path (current turn — unchanged)

```
POST /chat/message
  → _validate_images()                     [validation]
  → save_uploaded_image() × N              [disk + DB, collect artifact_ids]
  → _run_turn_in_background(artifact_ids)  [base64 still in request.images]
    → build_ai_turn_prep()
      → save_chat_message(role="user")      [returns user_msg_id]
      → wire_uploaded_images_to_message()  [sets chat_message_id on artifact rows]
      → claude_provider.generate()
        → sends base64 to Anthropic API    [unchanged]
```

## Multi-turn visual context (Paso 2 — implemented 2026-09-07)

```
POST /chat/message (turn N+1, no images)
  → _load_history(attach_images=True)
    → for each user ChatMessage in history:
        query FileArtifact WHERE chat_message_id = row.id AND artifact_type = "image"
        read bytes from disk, base64-encode
        → ChatHistoryItem.images = [{media_type, data}]
    → only the 2 most recent turns with images get loaded (_IMAGE_HISTORY_TURNS_MAX=2)
  → _history_to_messages()
    → image turns → [{type: "image", source: {...}}, {type: "text", text: ...}]
    → text turns  → {content: "string"} (merged if same role)
  → prior_messages sent to Anthropic API carries image blocks
    → model sees the image from turn N when answering in turn N+1
```

Note: the planner (routing model) never receives image blocks — `planner_prior_messages`
is built with `include_images=False` to avoid wasting tokens on a routing decision.

## Paso 3 — completed (2026-09-07)

### Backend endpoints (`backend/app/api/routes_files.py`)

All endpoints require authentication (guests get 401 — their files cannot be isolated
since all guest rows share `user_id=None`).

- `GET /files?page=1&size=20` — list user's FileArtifact rows (paginated, max 100 per page).
  Returns `{ok, total, page, size, files: [{id, artifact_type, filename, url, mime_type, source, size_bytes, created_at}]}`.
- `GET /files/export` — zip all user's binary files, downloads as `sity-archivos.zip`.
- `DELETE /files/{id}` — delete one file (disk + DB). Returns 404 for missing IDs or
  IDs belonging to another user (never reveals whether an ID exists in the system).
- `DELETE /files` — bulk delete all user's files (disk + DB).

Caddy routes: `handle /files* { reverse_proxy localhost:8000 }` added to both `:443` and `:80` blocks.

### Retention (`backend/app/chat/file_retention.py`)

Per-file retention policy (configurable, default 7 days). See §Ampliación below for
the updated behavior using `expires_at`. Legacy fallback: rows without `expires_at`
are deleted when `created_at < now - older_than_days`.

- `delete_old_file_artifacts(db)` — respects `is_permanent` (never deleted) and
  `expires_at` per row. Falls back to `created_at` cutoff for rows without `expires_at`.
  Idempotent: missing files on disk are silently skipped.
- `file_retention_loop()` / `start_file_retention_loop(loop)` — asyncio loop, runs
  every hour. Started from `main.py on_startup`.

### Frontend (`mobile/src/screens/VoiceScreen.tsx`)

The "Gestión de archivos" section (previously a placeholder) now shows:
- List of files with thumbnail (images) or audio icon, filename, date, size.
- Per-file delete button.
- "Exportar archivos (.zip)" button.
- "Eliminar todos" button with confirmation.
- Only visible for non-guest users.

i18n: new keys added to all 3 languages (`filesLoading`, `filesEmpty`, `filesDelete`,
`filesDeleteAll`, `filesDeleteAllConfirm`, `filesDeleteAllYes`, `filesExport`,
`filesExporting`). Existing `filesHint` updated from "Próximamente…" to the real description.

---

## Ampliación — 8 partes (2026-09-29)

### Parte 1 — campos nuevos en FileArtifact + settings de retención

`file_size_bytes`, `is_permanent`, `expires_at`, `semantic_extracted` added to the
model (see §FileArtifact table above). Migration: idempotent `ALTER TABLE … ADD COLUMN`
guarded by `PRAGMA table_info`.

`save_uploaded_image()` now accepts `retention_days` (default 7) and populates:
- `file_size_bytes = len(raw_bytes)`
- `expires_at = now + timedelta(days=retention_days)`

`register_capture_artifact()` similarly populates `file_size_bytes = path.stat().st_size`
and `expires_at`.

New endpoints in `routes_settings.py`:
- `GET /settings/file-retention` → `{file_retention_days: int}` (401 for guests)
- `PUT /settings/file-retention` → accepts `{file_retention_days: int}`, clamped 1–30

Config: `config/default_config.yaml` § `storage`:
```yaml
storage:
  file_retention_days: 7        # default auto-delete window (1–30 days)
  file_storage_limit_mb: 500    # per-user hard cap in megabytes
```

### Parte 2 — restricción de upload para invitados

`POST /chat/message` now returns 403 immediately when a guest sends images.
Registered users are unaffected.

### Parte 3 — límite de almacenamiento de 500 MB por usuario

New utility: `get_user_storage_bytes(db, user_id) -> int` — `func.sum(file_size_bytes)`
filtered by `user_id`.

Before saving any upload, `routes_chat.py` computes `_current + _incoming` bytes. If
the total exceeds `file_storage_limit_mb * 1024 * 1024`, the route returns 507
Insufficient Storage with a human-readable detail message. The limit is read from
`default_config.yaml` at request time; defaults to 500 MB.

### Parte 4 — borrado automático vía `expires_at`

`delete_old_file_artifacts()` rewritten:
- If `is_permanent=True`: row is never deleted.
- If `expires_at` is set: deleted when `expires_at < now` (timezone-naive comparison
  via `_naive()` helper — SQLite stores datetimes without tzinfo).
- Fallback: `created_at < now - older_than_days` for rows without `expires_at`.

Retention loop interval: **1 hour** (was 6 hours in the original Paso 3).

### Parte 5 — `PUT /files/{id}/permanent`

```
PUT /files/{id}/permanent
  Auth: User/Admin only (401 for guest, 404 for not-found or other user's file)
  Effect: is_permanent=True, expires_at=None
  Response: {ok: true, is_permanent: true}
```

### Parte 6 — extracción semántica asíncrona de imágenes

`backend/app/chat/image_semantic_extractor.py` — `extract_image_semantic_facts()`:
- Skipped when `ANTHROPIC_API_KEY` is not set or artifact is already `semantic_extracted`.
- Called in background (`loop.run_in_executor`) after each successful upload in `routes_chat.py`.
- Sends the image to Haiku via `provider.generate(AIRequest(..., images=[...]))` with
  a system prompt that extracts up to 3 stable facts about the user.
- Parses `{"facts": [...]}` JSON from the response; strips markdown fences; clamps each
  fact to 200 chars; keeps at most 3.
- Creates one `SemanticFact` row per fact; sets `FileArtifact.semantic_extracted=True`.
- Never raises — all errors are logged as WARN.

`_parse_facts(text) -> list[str]`: handles valid JSON, bad JSON, empty list, and
markdown-wrapped JSON blocks.

### Parte 7 — alerta de almacenamiento por push

`backend/app/notifications/storage_alert.py` — `maybe_send_storage_alert()`:
- No-op when `used_bytes / limit_bytes < 0.90`.
- Dispatches a push notification at ≥ 90 % (level `"warning"`) and ≥ 100 % (level `"full"`).
- Daily deduplication: `fact_id = f"storage_{level}_{user_id}_{today}"`.
- Called in `routes_chat.py` after all uploads are saved, using the post-upload total.
- Never raises.

### Parte 8 — sección Almacenamiento en frontend

`mobile/src/screens/VoiceScreen.tsx` additions:
- Progress bar showing `used_bytes / limit_bytes` with dynamic color (green → yellow →
  red at 90 %+).
- Retention selector (1 / 3 / 7 / 14 / 30 days) that calls `PUT /settings/file-retention`.
- Per-file "Conservar" button calls `PUT /files/{id}/permanent`; replaced by "Permanente"
  badge once marked.
- New GET endpoints consumed: `GET /files/storage-stats` (see below).

### New endpoints (Parte 5 + 8)

| Method | Route | Auth | Description |
|---|---|---|---|
| `GET` | `/files/storage-stats` | User/Admin | `{used_bytes, limit_bytes, file_count, permanent_count}` |
| `PUT` | `/files/{id}/permanent` | User/Admin | Mark file as permanent (no expiry) |

i18n: 6 new keys in 3 languages (`storageSection`, `storageUsed`, `storageRetentionLabel`,
`storageRetentionHint`, `storagePermanent`, `storageMarkPermanent`).
