# Getting Started / Setup Local

[English](#english) · [Español](#español)

---

## English

### Environments

The project uses two environments:

| Environment | Role |
|---|---|
| PC / Windows with WSL | LoRA training (RTX 3060 Ti), IDE editing |
| Raspberry Pi 4 (production) | Backend, panel, Home Assistant, camera, microphone, display |

Models are never trained on the Pi. The Pi handles backend, orchestration, display, tools, and sensors.

### Development workflow

```bash
# Connect to Pi via SSH
ssh pi@<PI_IP>

# Navigate to project
cd ~/sity

# Run tests
pytest

# Commit and push
git add <files>
git commit -m "..."
git push origin main
# GitHub Actions CI runs automatically
```

### Prerequisites (Pi)

- Python 3.11
- SQLite with FTS5 support
- `faster-whisper` (STT)
- `Piper` binary (TTS)
- Home Assistant in Docker
- `caddy` (reverse proxy)
- `cloudflared` (Cloudflare Tunnel)

### Prerequisites (WSL)

- CUDA-enabled PyTorch (for training)
- Unsloth (preferred for LoRA fine-tuning)
- Node.js (for frontend builds)

### Backend setup

```bash
# Create virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, etc.

# Start backend (development)
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend setup (mobile PWA)

```bash
cd mobile/
npm install

# Development server (port 5173)
npm run dev

# Production build
npm run build
# Output in mobile/dist/ — served by Caddy
```

### Key configuration

All defaults are in `backend/config/default_config.yaml`. Environment variables override config values.

Important settings:

| Setting | Location | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | Required for Claude API |
| `ADMIN_EMAIL` | `.env` | Admin account email |
| `ADMIN_PASSWORD` | `.env` | Admin account password |
| `VAPID_*` | `.env` | Web Push keys |
| `GOOGLE_*` | `.env` | Google OAuth credentials |
| `SPOTIFY_*` | `.env` | Spotify OAuth credentials |
| `RECAPTCHA_SECRET` | `.env` | reCAPTCHA v3 secret |

### Adding a new FastAPI router

Any new router with its own URL prefix must be added to the Caddyfile. Otherwise, requests fall through to the SPA and return a silent 404. After editing the Caddyfile:

```bash
sudo systemctl reload caddy
```

### Datetime handling

SQLite returns naive datetimes. API responses must normalize them to UTC. Use the Pydantic `@field_serializer` pattern:

```python
@field_serializer("created_at", "updated_at")
def serialize_dt(self, dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
```

### Safety rule

> If there are two options and one touches real runtime, choose the local/mock/manual option first. Do not make destructive changes without explicit confirmation.

---

## Español

### Entornos

El proyecto usa dos entornos. Ver tabla en la sección en inglés. Los modelos nunca se entrenan en la Pi.

### Flujo de desarrollo

```bash
# Conectar a la Pi por SSH
ssh pi@<PI_IP>
cd ~/sity

# Ejecutar tests
pytest

# Commit y push
git add <archivos>
git commit -m "..."
git push origin main
# GitHub Actions CI corre automáticamente
```

### Setup del backend

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, etc.
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### Setup del frontend (PWA móvil)

```bash
cd mobile/
npm install
npm run dev        # dev server en puerto 5173
npm run build      # build de producción → mobile/dist/
```

### Añadir un nuevo router FastAPI

Cualquier router con su propio prefijo de URL debe añadirse al Caddyfile. Si no, las peticiones caen al SPA y devuelven un 404 silencioso.

### Manejo de datetimes

SQLite devuelve datetimes sin zona horaria. Las respuestas API deben normalizarlas a UTC. Usar el patrón `@field_serializer` de Pydantic.

### Regla de seguridad

> Si hay dos opciones y una toca runtime real, elegir primero la opción local/mock/manual. No hacer cambios destructivos sin confirmación explícita.
