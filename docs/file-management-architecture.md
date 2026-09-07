# File Management Architecture

## Context

**Paso 1** (2026-09-07): every image or audio file that enters the system is persisted
to disk and registered in the `FileArtifact` inventory table.

**Paso 2** (2026-09-07): multi-turn visual context — uploaded images are now included
in prior_messages when Claude generates responses, so the model can see images from
recent turns. The `FileArtifact.chat_message_id` field is populated and used for this.

Paso 3 (frontend: list, delete individually/in bulk, export as zip) is deferred.

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
chat_message_id INTEGER NULL     — id of the ChatMessage that owns this file
                                   (wired in Paso 2; used for image history)
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

## Paso 3 — pending (file manager frontend)

- `GET /files` — list user's FileArtifact rows (paginated)
- `DELETE /files/{id}` — delete one file (disk + DB row)
- `DELETE /files` — bulk delete
- `GET /files/export` — zip all user's files as binary download
- Consider retention policy (auto-delete uploads older than N days)
