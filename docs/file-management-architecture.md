# File Management Architecture

## Context

Paso 1 of the file management feature: every image or audio file that enters the
system is now persisted to disk and registered in the `FileArtifact` inventory table.
Paso 2 (frontend: list, delete individually/in bulk, export as zip) is deferred.

## FileArtifact table

```
fileartifact
────────────────────────────────────────────────────────────────────
id              INTEGER PRIMARY KEY
user_id         INTEGER  NULL    — None for guest sessions; indexed
artifact_type   TEXT             — "image" | "audio"
filename        TEXT             — bare filename, e.g. "a1b2.jpg"
rel_path        TEXT             — path relative to PROJECT_ROOT
                                   e.g. "uploads/images/a1b2.jpg"
                                        "captures/camera/snap.jpg"
mime_type       TEXT  NULL
source          TEXT             — "chat_upload" | "camera_capture"
chat_message_id INTEGER NULL     — reserved for Paso 2 (always NULL now)
created_at      DATETIME
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
3. Insert `FileArtifact` row
4. Return normally — the `request.images` base64 is **unchanged** and still passed
   to the Claude API. The Anthropic API requires base64; there is no URL-based image
   input. The file on disk is for the inventory only; the model still receives base64.

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

## Model call path (unchanged)

```
POST /chat/message
  → _validate_images()          [validation]
  → save_uploaded_image() × N   [NEW: disk + DB, best-effort]
  → _run_turn_in_background()   [base64 still in request.images]
    → ai_orchestrator
      → claude_provider.generate()
        → sends base64 to Anthropic API  [unchanged]
```

## Paso 2 — pending (file manager frontend)

Decided in session 2026-09-07. Not yet implemented.

- `GET /files` — list user's FileArtifact rows (paginated)
- `DELETE /files/{id}` — delete one file (disk + DB row)
- `DELETE /files` — bulk delete
- `GET /files/export` — zip all user's files as binary download
- Wire `chat_message_id` in FileArtifact to link files to the message that used them
- Consider retention policy (auto-delete uploads older than N days)
