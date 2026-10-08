# File Management / Gestión de Archivos

[English](#english) · [Español](#español)

---

## English

### Overview

All uploaded and captured files are saved to disk and registered in the `FileArtifact` table. Users can browse, delete, and export their files. Guests cannot use the file manager.

### File sources

| Source | Path | Registration |
|---|---|---|
| Chat image upload | `uploads/images/` | On upload, linked to user message |
| Camera capture | `captures/camera/` | From orchestrator and deferred action runs |
| Audio capture | `captures/audio/` | From orchestrator and deferred action runs |

### `FileArtifact` table

| Field | Description |
|---|---|
| `user_id` | Owner (null for guests) |
| `type` | `image` or `audio` |
| `filename` | Stored filename |
| `path` | Relative path on disk |
| `mime_type` | MIME type |
| `source` | How it arrived (upload / camera / audio) |
| `chat_message_id` | Linked chat message |
| `created_at` | Creation timestamp |
| `file_size` | Bytes |
| `is_permanent` | Skip auto-deletion if true |
| `expires_at` | Auto-deletion deadline |
| `semantic_extracted` | Whether background extraction has run |

Every query that exposes files must filter by `user_id`.

### Retention and limits

| Setting | Default | Range |
|---|---|---|
| Retention period | 7 days | 1–30 days |
| Storage cap per user | 500 MB | — |
| Cleanup frequency | Hourly background loop | — |

- **Permanent files** (`is_permanent = true`) are never auto-deleted
- Files missing on disk are skipped during cleanup (logged, not raised)
- Uploads exceeding storage cap return HTTP 507
- Push alerts at 90% and 100% of cap (at most once per day per level)

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/files` | List user's files |
| `GET` | `/files/export` | Download all files as zip |
| `DELETE` | `/files/{id}` | Delete single file |
| `DELETE` | `/files` | Bulk delete |
| `GET` | `/files/storage-stats` | Storage usage |
| `PUT` | `/files/{id}/permanent` | Mark as permanent |
| `GET` | `/settings/file-retention` | Read retention setting |
| `PUT` | `/settings/file-retention` | Update retention setting |

Guests receive HTTP 403 on all file endpoints.

### Multi-turn visual context

The two most recent turns with images are reloaded into history as base64 image blocks. The routing planner never receives image blocks (saves tokens).

### Background semantic extraction

After upload, a background job sends the image to Haiku and stores up to 3 `SemanticFact` rows. Failures are logged and never raised — extraction failure does not affect the upload.

---

## Español

### Visión general

Todos los archivos subidos y capturados se guardan en disco y se registran en la tabla `FileArtifact`. Los usuarios pueden navegar, eliminar y exportar sus archivos. Los guest no pueden usar el gestor de archivos.

### Fuentes de archivos

Ver tabla en la sección en inglés.

### Tabla `FileArtifact`

Ver tabla en la sección en inglés. Toda consulta que exponga archivos debe filtrar por `user_id`.

### Retención y límites

- Período por defecto: 7 días (rango 1–30)
- Cap de almacenamiento por usuario: 500 MB
- Limpieza: bucle en background cada hora
- Archivos permanentes (`is_permanent = true`): nunca se auto-eliminan
- Archivos faltantes en disco: se saltan (log, sin excepción)
- Subidas que superan el cap: HTTP 507
- Alertas push al 90% y 100% del cap (máximo una vez al día por nivel)

### Endpoints

Ver tabla en la sección en inglés. Los guest reciben HTTP 403 en todos los endpoints de archivos.

### Contexto visual multi-turno

Los dos turnos más recientes con imágenes se recargan en el historial como bloques de imagen base64. El planificador de enrutamiento nunca recibe bloques de imagen (ahorra tokens).

### Extracción semántica en background

Tras la subida, un job en background envía la imagen a Haiku y almacena hasta 3 filas `SemanticFact`. Los fallos se loguean y nunca se propagan — un fallo en la extracción no afecta a la subida.
