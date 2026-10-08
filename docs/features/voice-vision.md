# Voice & Vision / Voz y Visión

[English](#english) · [Español](#español)

---

## English

### Voice

Sity processes audio entirely on-device using local binaries — no cloud STT or TTS APIs.

#### Speech-to-Text (STT)

**Engine**: `faster-whisper` (locally installed on Pi)

- Model: upgraded from `base` to `small` during project evolution
- Voice input activates when the user sends an audio message
- A guard removes sensor tools when input is voice (to avoid accidental tool calls)

#### Text-to-Speech (TTS)

**Engine**: `Piper` (binary installed on Pi)

- Generates audio from Sity's text response
- Voice settings control:
  - When audio is generated (always / on request / never)
  - Whether text is shown alongside audio
  - How long responses are handled (truncation for long replies)

#### Voice screen (PWA)

The mobile `VoiceScreen` provides:
- Audio recording and playback
- File list with storage usage indicator
- Retention selector (how long to keep audio files)
- Per-file "keep permanently" button (`Conservar`)

### Vision (image input)

Sity can process images attached to messages.

**Phase 1** (current): Images are sent to the Claude API (Haiku) without local storage beyond `FileArtifact` registration. Not cached in prompt history beyond recent turns.

**Multi-turn visual context**: The two most recent turns with images are reloaded into history as base64 image blocks. The routing planner never receives image blocks (saves tokens).

**Semantic extraction**: Uploaded images are processed by a background job that sends them to Haiku and stores up to 3 `SemanticFact` rows per image. Failures are logged and never raised.

**Storage**: Images saved to `uploads/images/`, registered in `FileArtifact` table with owner, type, path, MIME type, source, linked chat message.

**Phase 2** (planned): Move image handling to a local multimodal model. No decision made on which model yet.

**Image retention**: See [file-management.md](file-management.md) for retention policies, storage limits, and expiry.

**Security**: Guests receive HTTP 403 when trying to upload images. Each `GET /uploads/images/{filename}` must have authentication and ownership check (open finding A1 from 2026-09-16 audit).

---

## Español

### Voz

Sity procesa audio completamente en el dispositivo usando binarios locales — sin APIs de nube para STT o TTS.

#### Speech-to-Text (STT)

**Motor**: `faster-whisper` (instalado localmente en la Pi)

- Modelo: actualizado de `base` a `small` durante la evolución del proyecto
- Un guard elimina las tools de sensores cuando el input es voz (para evitar tool calls accidentales)

#### Text-to-Speech (TTS)

**Motor**: `Piper` (binario instalado en la Pi)

Los settings de voz controlan cuándo se genera audio, si el texto se muestra junto al audio y cómo se manejan las respuestas largas.

### Visión (input de imagen)

**Fase 1** (actual): Las imágenes se envían a la API de Claude (Haiku) sin almacenamiento local más allá del registro en `FileArtifact`. Los dos turnos más recientes con imágenes se recargan en el historial. El planificador de enrutamiento nunca recibe bloques de imagen (ahorra tokens).

**Extracción semántica en background**: Las imágenes subidas se procesan por un job en background que las envía a Haiku y almacena hasta 3 filas `SemanticFact` por imagen.

**Fase 2** (planificada): Mover el procesamiento de imágenes a un modelo multimodal local.

**Seguridad**: Los guest reciben HTTP 403 al intentar subir imágenes. El endpoint `GET /uploads/images/{filename}` necesita autenticación y verificación de propiedad (hallazgo A1 de la auditoría 2026-09-16, pendiente).
