# Deployment / Despliegue

[English](#english) · [Español](#español)

---

## English

### Infrastructure

```
Raspberry Pi 4
├── sity-backend (systemd)     FastAPI on localhost:8000
├── caddy (systemd)            Reverse proxy, TLS termination
├── cloudflared (systemd)      Cloudflare Tunnel → sity.aletm.com
├── home-assistant (Docker)    Home automation abstraction
└── sity-panel (Electron)      Internal monitoring (not user-facing)
```

### Caddy configuration

Caddy is the single point of TLS and auth headers. The backend listens on `localhost:8000` only.

Every new FastAPI router with its own URL prefix must be added to the Caddyfile:

```caddyfile
# Example — add routes for new prefixes
route /api/* {
    reverse_proxy localhost:8000
}
route /uploads/* {
    reverse_proxy localhost:8000
}
```

After any Caddyfile change:

```bash
sudo systemctl reload caddy
```

**Note**: The dev proxy in `mobile/vite.config.ts` omits `/uploads` and `/files` by default (open finding A8 from audit). Add them if needed for local development.

### Deploying the frontend

```bash
# Build the PWA
cd mobile/
npm run build

# Caddy serves mobile/dist/ automatically — no service restart needed
```

The `sity-frontend` systemd service is a Vite dev server on port 5173. It is **not** used in production — do not confuse them.

**Installed Android PWAs (WebAPK)** maintain a separate browser context and may show an old version after deploy. Fix: clear storage in Android settings or reinstall the PWA.

### Deploy script

```bash
./deploy.sh
```

Behavior:
1. Checks if files in `mobile/src/` or `mobile/public/` are newer than `mobile/dist/` bundle
2. If yes: runs `npm run build` in `mobile/`
3. Restarts `sity-backend` systemd service

Caddy needs a separate reload only when its config changes.

### Service management

```bash
# Status
sudo systemctl status sity-backend
sudo systemctl status caddy
sudo systemctl status cloudflared

# Restart
sudo systemctl restart sity-backend
sudo systemctl restart caddy

# Logs (JSONL in data/logs/)
journalctl -u sity-backend -f
```

### Log system

Logs are JSONL files in `data/logs/`, split into application and audit logs.

**What is logged** (by phase):
- Tool calls (Spotify, Google, Home Assistant)
- SSE events, audio, memory operations
- Frontend errors, auth events
- `achievement_unlocked`, `tool_chain_continued`, cognition step outcomes

**What is NOT logged**:
- Synthesized text or TTS output (only lengths)
- Audio transcriptions (only lengths)
- Task context values (only key names)

Logs older than 14 days are purged automatically every 10 minutes.

### Verifying a frontend deployment

After `npm run build` and page reload:
1. Open DevTools → Network
2. Confirm bundle hash matches the new build timestamp
3. Check for a Service Worker in "waiting to activate" state

If a Service Worker is stuck:
```javascript
// In browser console
navigator.serviceWorker.getRegistrations().then(regs => regs.forEach(r => r.unregister()))
```
The service worker sends a `SKIP_WAITING` message and reloads the page when the controller changes.

---

## Español

### Infraestructura

Ver diagrama en la sección en inglés. El backend escucha solo en `localhost:8000`. Caddy gestiona TLS y los headers de auth.

### Configuración de Caddy

Todo nuevo router de FastAPI con su propio prefijo debe añadirse al Caddyfile. Tras cualquier cambio:

```bash
sudo systemctl reload caddy
```

**Nota**: El dev proxy en `mobile/vite.config.ts` omite `/uploads` y `/files` por defecto (hallazgo A8 de la auditoría). Añadirlos si se necesitan en desarrollo local.

### Desplegar el frontend

```bash
cd mobile/
npm run build
# Caddy sirve mobile/dist/ automáticamente — no requiere reinicio del servicio
```

El servicio `sity-frontend` es un servidor Vite dev en el puerto 5173. **No** se usa en producción.

**PWAs Android instaladas (WebAPK)**: mantienen un contexto separado y pueden mostrar la versión antigua tras el despliegue. Fix: borrar almacenamiento en ajustes de Android o reinstalar la PWA.

### Gestión de servicios

```bash
sudo systemctl status sity-backend
sudo systemctl status caddy
sudo systemctl restart sity-backend
journalctl -u sity-backend -f
```

### Sistema de logs

Logs JSONL en `data/logs/`, divididos en logs de aplicación y de auditoría. Los logs de más de 14 días se purgan automáticamente cada 10 minutos.

**Lo que se loguea**: llamadas a tools, eventos SSE, audio, memoria, errores frontend, auth.

**Lo que NO se loguea**: texto sintetizado ni transcripciones (solo longitudes), valores de task context (solo nombres de clave).

### Verificar despliegue del frontend

Tras build y recarga de página: verificar en DevTools que el hash del bundle coincide con el nuevo build y que no hay Service Worker en "waiting to activate".
