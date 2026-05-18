# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse en una Raspberry Pi/RasPad y vivir en un entorno local controlado.

El objetivo del proyecto no es solo tener un chatbot, sino una asistente con personalidad configurable, memoria conversacional, acceso controlado al sistema, integración progresiva con hardware y capacidad de ejecutar acciones reales con confirmación explícita.

Actualmente Sity usa Claude como proveedor principal de IA, con una arquitectura preparada para añadir fallback a otros modelos en el futuro.

---

## Estado actual

### Funciona

- Backend FastAPI.
- Frontend web con chat.
- Integración con Claude API.
- Personalidad dinámica configurable.
- Sliders de personalidad.
- Modificación de personalidad desde chat mediante tools.
- Historial persistente de conversación.
- Uso de SQLite como base local.
- Logs y trazas.
- Debug tools.
- Lectura de estado del sistema.
- Lectura de estado Git.
- Acciones Git con confirmación.
- Acciones systemd con confirmación.
- Gestión dinámica de allowlist de servicios.
- Servicios systemd versionados en el repo.
- Servicio de prueba `sity-test`.
- Fast paths locales para evitar gasto innecesario de tokens.
- Presupuesto diario local de tokens y avisos de uso.
- Prompt/tool routing corregido para no usar debug en conversación normal.
- Reconocimiento de personalidad actual desde el estado inyectado por backend.
- Cámara USB detectada y funcionando.
- Micrófono USB de webcam detectado y grabando.
- Workaround de audio RasPad 3 documentado.
- Audio HDMI funcionando mediante pipeline ALSA Loopback → IEC958.
- Vivaldi y VLC funcionando con el pipeline custom de audio.

---

## Arquitectura general

```text
frontend/
  Interfaz web de chat y sliders.

backend/
  API FastAPI.
  Núcleo de conversación.
  Gateway IA.
  Providers.
  Tools.
  Confirmaciones.
  Acceso controlado a sistema/Git.
  Futuras integraciones de sensores.

config/
  Configuración local versionada.

data/
  SQLite, logs y datos runtime.
  Ignorado por git.

deploy/
  Plantillas systemd, sudoers y documentación de despliegue.

scripts/
  Scripts de desarrollo, instalación y estado.

services/
  Servicios auxiliares del proyecto.

captures/
  Capturas temporales de cámara/audio.
  Ignorado por git salvo `.gitkeep`.
```

---

## Backend

El backend expone, entre otros:

```text
GET  /health
POST /chat/message
GET  /chat/current
GET  /settings/personality
POST /settings/personality/adjust
GET  /debug/events/recent
GET  /debug/last-trace
```

Endpoint principal:

```text
POST /chat/message
```

Ejemplo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
```

Health check:

```bash
curl http://localhost:8000/health
```

---

## Frontend

El frontend permite:

- Chatear con Sity.
- Ver respuestas en formato texto.
- Ver proveedor/modelo/trace.
- Ver uso de tokens.
- Ajustar personalidad con sliders.
- Mantener conversación tras refrescar la página.
- Mostrar historial persistente desde backend.
- Consultar paneles de debug.

El frontend usa:

```text
VITE_SITY_API_BASE
```

Ejemplo:

```env
VITE_SITY_API_BASE=http://192.168.1.133:8000
```

---

## IA / Claude

Actualmente Sity usa Claude como proveedor principal.

Modelo usado durante el desarrollo:

```text
claude-haiku-4-5-20251001
```

Claude se usa para:

- Conversación.
- Interpretación flexible de intención.
- Decidir cuándo usar tools.
- Transformar peticiones naturales en acciones estructuradas.
- Responder con personalidad actual.

El backend se encarga de:

- Seguridad.
- Confirmaciones.
- Fast paths deterministas.
- Ejecución de acciones.
- Persistencia.
- Logs.
- Control de costes.

---

## Personalidad

Sity tiene personalidad parametrizable. Los parámetros actuales incluyen:

```text
sarcasm_level
rudeness_level
warmth_level
honesty_level
initiative_level
dry_humor_level
tsundere_level
contrarian_level
patience_level
refusal_chance
helpfulness_level
verbosity_level
melancholy_level
```

Estos parámetros pueden cambiarse:

1. Desde el frontend, con sliders.
2. Desde API.
3. Desde chat, mediante tool use de Claude.

Ejemplos:

```text
sube la melancolía al 90%
pon todos los parámetros al 50%
baja el sarcasmo al 30%
hazte menos borde pero mantén algo de sarcasmo
```

La personalidad actual inyectada por el backend es la fuente de verdad.

Si el usuario cambia sliders desde el frontend, Sity debe usar los valores actuales recibidos en el prompt. No necesita una confirmación de tool para reconocer cambios hechos desde la UI.

Solo debe hablar de "cambio aplicado por tool" cuando el backend indique explícitamente que una tool de personalidad ha ejecutado un cambio.

---

## Memoria conversacional

Sity mantiene historial persistente de conversación en backend.

Esto permite:

- Recargar la UI sin perder conversación.
- Usar contexto anterior.
- Evitar depender de memoria temporal del frontend.
- Consultar `/chat/current` para reconstruir la conversación.

La memoria de frontend se ha reducido para evitar contradicciones. El backend es la fuente principal de verdad.

---

## Tools

Sity usa tools para acciones estructuradas.

Tipos actuales:

```text
Personality tools
Debug tools
System read tools
Git read tools
Git action tools
System action tools
System config tools
No-action / respuesta normal
```

Las tools críticas no se ejecutan directamente. Se crea una acción pendiente y se exige confirmación.

Las herramientas de debug solo deben usarse cuando el usuario pide explícitamente:

```text
logs
trazas
errores
eventos
tools ejecutadas
diagnóstico técnico
auditoría
```

No deben usarse para conversación normal, frases ambiguas o seguimiento contextual.

---

## Confirmation Manager

Las acciones que modifican el sistema o Git pasan por un `Confirmation Manager`.

Flujo:

```text
1. Usuario pide una acción.
2. Backend crea pending_action.
3. Sity muestra qué va a hacer.
4. Usuario confirma.
5. Backend ejecuta localmente.
```

Ejemplo:

```text
Usuario:
reinicia el frontend

Sity:
Acción pendiente creada: Reiniciar servicio sity-frontend

Para ejecutarla, confirma con:
confirmo ejecutar act_xxxxxxxx

También puedes decir:
sí, reinicia frontend
```

Confirmaciones soportadas:

```text
confirmo ejecutar act_xxxxxxxx
sí, hazlo
dale
sí, reinicia frontend
sí, reinicia sity-test
sí, añade sity-test
```

Reglas importantes:

- Si hay varias acciones pendientes, una confirmación genérica no debe adivinar.
- Si una acción ya fue ejecutada, no se repite.
- Si un ID no existe o está expirado, se responde localmente.
- Las confirmaciones viejas no caen en Claude.
- Repetir una orden no cuenta como confirmación.
- Si ya existe una acción pendiente equivalente, se reutiliza.
- Las acciones duplicadas se detectan.
- La confirmación contextual exige intención explícita.

---

## Fast paths locales

Para ahorrar tokens, muchas acciones obvias no pasan por Claude.

Ejemplos locales con 0 tokens:

```text
qué servicios puedes controlar?
reinicia el frontend
reinicia sity-test
haz fetch del repo sity
haz pull del repo sity
cambia a la rama main
añade sity-test a servicios permitidos
confirmo ejecutar act_xxxxxxxx
```

Criterio general:

```text
Backend local:
- Seguridad.
- Confirmaciones.
- Acciones deterministas.
- Dedupe.
- Estados de acciones.

Claude:
- Interpretación flexible.
- Conversación.
- Decidir si hace falta tool.
- Explicar resultados.
```

---

## Git

Sity puede leer estado Git:

```text
status
log
branches
remotes
diff
```

Y puede proponer acciones Git con confirmación:

```text
fetch
pull --ff-only
push
crear rama
cambiar de rama
commit
```

Ejemplos:

```text
cómo está el repo sity?
qué últimos commits tiene el repo sity?
haz pull del repo sity
haz fetch del repo sity
crea una rama feature/test
cambia a la rama main
```

Las acciones modificadoras requieren confirmación.

---

## System Access

Sity puede leer información del sistema:

```text
estado básico
CPU/RAM
disco
procesos
servicios permitidos
directorios permitidos
```

También puede controlar servicios systemd permitidos:

```text
start
stop
restart
```

Actualmente se usan:

```text
sity-backend
sity-frontend
sity-test
```

---

## Allowlist dinámica de servicios

Sity puede modificar la allowlist de servicios con confirmación.

Ejemplos:

```text
qué servicios puedes controlar?
añade sity-test a servicios permitidos
quita sity-test de servicios permitidos
```

Esto modifica:

```text
config/system_access.yaml
```

Importante:

- Añadir un servicio a la allowlist no crea el servicio systemd.
- Quitar un servicio de la allowlist no borra el servicio systemd.
- Solo cambia qué servicios puede consultar/controlar Sity.
- La modificación de allowlist requiere confirmación.

---

## Servicios systemd

El proyecto incluye plantillas versionadas en:

```text
deploy/systemd/
```

Servicios actuales:

```text
sity-backend.service
sity-frontend.service
sity-test.service
```

### sity-backend

Servicio FastAPI/Uvicorn.

```text
http://localhost:8000
```

### sity-frontend

Servicio Vite dev server.

```text
http://localhost:5173
```

En red local:

```text
http://192.168.1.133:5173
```

### sity-test

Servicio HTTP mínimo para pruebas.

```text
http://localhost:8099
```

Devuelve:

```text
sity service test
```

Está pensado para probar control de servicios sin levantar algo pesado como Minecraft.

---

## Sudoers

La allowlist sudoers está versionada en:

```text
deploy/sudoers/sity
```

Permite a `alex` ejecutar sin password únicamente:

```text
systemctl start/stop/restart sity-backend
systemctl start/stop/restart sity-frontend
systemctl start/stop/restart sity-test
```

No se concede sudo general.

---

## Instalación de servicios

Script:

```bash
./scripts/install_systemd_services.sh
```

Hace:

```text
1. Copia servicios a /etc/systemd/system/
2. Copia sudoers a /etc/sudoers.d/sity
3. Valida sudoers con visudo
4. Recarga systemd
5. Habilita servicios
```

Después se pueden arrancar manualmente:

```bash
sudo systemctl start sity-backend
sudo systemctl start sity-frontend
sudo systemctl start sity-test
```

---

## Estado rápido de servicios

Script:

```bash
./scripts/status_services.sh
```

Muestra:

```text
is-enabled
is-active
health backend
respuesta de sity-test
```

---

## Cámara y micrófono

Hardware detectado:

```text
Cámara:
Full HD webcam
/dev/video0
/dev/video1

Micrófono:
Full HD webcam
ALSA card webcam
PipeWire source Full HD webcam Mono
```

La cámara funciona, pero necesita tiempo para autoexposición. Las capturas deben usar `fswebcam` con `--skip 20` o `--skip 30`.

Ejemplo manual:

```bash
fswebcam -d /dev/video0 -r 1280x720 --no-banner --skip 20 captures/camera/test.jpg
```

El micro de la webcam graba correctamente.

Ejemplo manual:

```bash
arecord -D plughw:CARD=webcam,DEV=0 -d 5 -f cd captures/audio/test-webcam.wav
```

Importante:

- No usar `Loopback` como micrófono real.
- `Loopback` forma parte del pipeline de audio HDMI.
- Cámara y micrófono son sensores sensibles.
- Capturar foto o grabar audio debe requerir confirmación.
- Listar dispositivos puede ser local/directo.

---

## Audio RasPad 3

El RasPad 3 no expone correctamente HPD en HDMI. El driver `vc4-hdmi` no ofrece audio PCM normal y solo expone `IEC958_SUBFRAME_LE`.

Para resolverlo, el sistema usa un pipeline custom:

```text
Vivaldi / VLC / ALSA
  -> snd-aloop Loopback
  -> arecord hw:Loopback,1,0
  -> pcm2iec958.py
  -> aplay hw:vc4hdmi0,0 IEC958_SUBFRAME_LE
  -> HDMI
```

Componentes documentados en:

```text
deploy/audio/
```

Puntos importantes:

- `snd-aloop` crea una tarjeta virtual Loopback.
- `/etc/asound.conf` redirige ALSA `default` a `hw:Loopback,0`.
- `pcm2iec958.py` convierte PCM S16LE a `IEC958_SUBFRAME_LE`.
- `hdmi-audio-forward.service` mantiene el pipeline activo.
- WirePlumber debe ignorar Loopback para evitar feedback con el micrófono.
- Vivaldi 32-bit usa ALSA directo y necesita que `default` apunte al Loopback.
- VLC necesita `aout=alsa` y `alsa-audio-device=hw:Loopback,0`.

No tocar a ciegas:

```text
/etc/asound.conf
/etc/modules-load.d/snd-aloop.conf
/home/alex/.local/bin/pcm2iec958.py
~/.config/systemd/user/hdmi-audio-forward.service
~/.config/wireplumber/main.lua.d/51-default-sink.lua
~/.config/vlc/vlcrc
```

---

## Configuración principal

Archivo:

```text
config/system_access.yaml
```

Define:

```text
system_access.read.allowed_paths
system_access.read.allowed_services
system_access.safe_actions.allowed_services
git_access.read.allowed_repositories
```

---

## Variables de entorno

Archivo local no versionado:

```text
.env
```

Incluye claves como:

```text
ANTHROPIC_API_KEY
OPENAI_API_KEY
PC_AGENT_TOKEN
SITY_ENV
```

No debe subirse a Git.

Frontend local:

```text
frontend/.env.local
```

Ejemplo:

```env
VITE_SITY_API_BASE=http://192.168.1.133:8000
```

---

## Logs y datos

Runtime local:

```text
data/
```

Incluye:

```text
app.db
logs
audit logs
```

Debe permanecer fuera de Git.

Logs systemd:

```bash
journalctl -u sity-backend -n 80 --no-pager
journalctl -u sity-frontend -n 80 --no-pager
journalctl -u sity-test -n 80 --no-pager
```

---

## Capturas temporales

Directorio:

```text
captures/
```

Usado para futuras capturas de cámara/audio.

Debe estar ignorado por git salvo `.gitkeep`.

Política pendiente:

- No acumular capturas indefinidamente.
- Borrar por antigüedad.
- Borrar por número máximo de archivos.
- Borrar por tamaño máximo total.
- Permitir comando tipo `limpia capturas antiguas`.

---

## Seguridad

Principios actuales:

```text
1. Lectura directa solo en zonas permitidas.
2. Acciones modificadoras requieren confirmación.
3. Servicios controlables limitados por allowlist.
4. Sudoers limitado a comandos concretos.
5. Sin shell arbitraria.
6. Sin sudo general.
7. Las acciones viejas no se reejecutan.
8. Las acciones duplicadas se detectan.
9. Confirmación contextual solo con intención explícita.
10. Las herramientas de debug no se usan para conversación normal.
11. Cámara y micro no se activan sin confirmación.
12. Audio Loopback se trata como dispositivo virtual, no como micro real.
```

Regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar solo si se confirma.
```

Para capacidades que salen del entorno local —internet, Bluetooth, WiFi, Google, correo, calendario o archivos externos— Sity debe pedir permiso antes de actuar, explicar qué va a consultar o modificar, y dejar trazabilidad en logs/auditoría.

---

## Desarrollo

### Backend

Si el backend está corriendo como servicio, lanzarlo manualmente puede dar:

```text
ERROR: [Errno 98] Address already in use
```

Eso es normal: el puerto `8000` ya está ocupado por `sity-backend.service`.

Reiniciar backend:

```bash
sudo systemctl restart sity-backend
```

Comprobar salud:

```bash
curl http://localhost:8000/health
```

### Frontend

Reiniciar frontend:

```bash
sudo systemctl restart sity-frontend
```

Abrir:

```text
http://192.168.1.133:5173
```

---

## Comandos útiles

### Backend

```bash
sudo systemctl restart sity-backend
curl http://localhost:8000/health
```

### Frontend

```bash
sudo systemctl restart sity-frontend
```

### Servicios

```bash
./scripts/status_services.sh
./scripts/install_systemd_services.sh
```

### Sity test service

```bash
curl http://localhost:8099
```

### SQLite

```bash
sqlite3 data/app.db
```

Expirar acciones pendientes:

```bash
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"
```

### Chat API

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"qué servicios puedes controlar?"}' | python3 -m json.tool
```

### CORS / preflight

```bash
curl -i -X OPTIONS http://localhost:8000/chat/message \
  -H "Origin: http://192.168.1.133:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```

### Cámara

```bash
fswebcam -d /dev/video0 -r 1280x720 --no-banner --skip 20 captures/camera/test.jpg
```

### Micrófono real de webcam

```bash
arecord -D plughw:CARD=webcam,DEV=0 -d 5 -f cd captures/audio/test-webcam.wav
```

### Audio HDMI workaround

```bash
systemctl --user status hdmi-audio-forward.service
systemctl --user restart hdmi-audio-forward.service
```

---

## Roadmap

### Core pendiente

- Mejorar manejo de múltiples acciones pendientes.
- Añadir vista/listado de pending actions desde chat.
- Permitir cancelar acciones pendientes desde chat.
- Deduplicar también acciones Git.
- Mejorar mensajes de confirmación para usar nombres humanos en vez de nombres systemd.
- Añadir tests automatizados para confirmation manager.
- Añadir migraciones de base de datos si el esquema crece.
- Mejorar compactación de historial largo.
- Evitar que `/chat/current` devuelva mensajes antiguos cuando debería devolver los últimos.

### System Access

- Añadir gestión de allowlist de rutas.
- Añadir lectura segura de archivos permitidos.
- Añadir logs de servicios systemd.
- Añadir health checks por servicio.
- Añadir plantillas para crear nuevos servicios systemd desde planes confirmados.
- Añadir acciones críticas planificadas para instalar/configurar servicios.
- Integrar servicios pesados como Minecraft solo bajo confirmación.
- Permitir añadir/quitar servicios conforme el usuario los cree o elimine.

### Git

- Prevalidación más inteligente antes de pull/push/commit.
- Proponer stash/commit si el working tree está sucio.
- Crear PRs en GitHub.
- Leer issues y pull requests.
- Integración con GitHub CLI o API.
- Gestión segura de ramas remotas.
- Deduplicar acciones Git pendientes igual que system actions.

### Sentidos / Hardware

Pendiente para la siguiente fase:

- Detectar orientación de RasPad 3.
- Leer sensores disponibles.
- Detectar cámara.
- Detectar micrófono integrado en la cámara.
- Capturar snapshot de cámara.
- Grabar muestra de audio.
- Añadir análisis de imagen.
- Añadir transcripción de audio.
- Añadir wake word o modo escucha.
- Detectar estado de pantalla.
- Explorar integración con sensor de movimiento/orientación.

### Cámara y micrófono

Pendiente:

- Listar dispositivos de vídeo.
- Listar dispositivos de audio.
- Capturar una imagen bajo petición.
- Grabar audio corto bajo petición.
- Guardar capturas en ruta controlada.
- No activar cámara/micrófono sin confirmación.
- Añadir indicadores visibles/logs cuando se usen sensores.
- Integrar transcripción.
- Integrar descripción de imágenes.
- Ignorar dispositivos virtuales como `Loopback` al elegir micro.
- Usar `fswebcam --skip 20/30` para evitar capturas oscuras.
- Usar el micro real de la webcam, no la salida del sistema.

### Retención de archivos generados

Pendiente:

- No acumular capturas de cámara/audio indefinidamente.
- Añadir limpieza automática de `captures/camera/` y `captures/audio/`.
- Configurar retención por:
  - antigüedad
  - número máximo de archivos
  - tamaño máximo total
- Añadir comando local:
  - `limpia capturas antiguas`
  - `borra audios temporales`
  - `borra fotos de prueba`
- Las capturas sensibles deben poder borrarse bajo petición.

### Audio routing

Pendiente:

- Detectar dispositivos virtuales como `Loopback`.
- No usar `Loopback` como micrófono por defecto.
- Exponer estado del pipeline HDMI audio forward.
- Tool local para comprobar si `hdmi-audio-forward.service` está activo.
- Documentar RasPad 3 audio workaround.
- Evitar que futuras tools de audio rompan:
  - `/etc/asound.conf`
  - WirePlumber
  - `snd-aloop`
  - `pcm2iec958.py`
  - configuración VLC/Vivaldi

### Conectividad local

Pendiente:

- Integración con Bluetooth de la Raspberry.
- Escaneo de dispositivos Bluetooth cercanos.
- Emparejamiento controlado de dispositivos.
- Transferencia de archivos por Bluetooth con confirmación.
- Integración con WiFi.
- Lectura de redes WiFi visibles.
- Diagnóstico de conectividad local.
- Gestión segura de conexiones conocidas.
- Compartición o recepción de archivos en red local.
- Detección de dispositivos de la LAN.
- Acciones de red siempre bajo allowlist y confirmación.

### Internet / Web Access

Pendiente:

- Añadir herramienta de búsqueda web.
- Sity debe preguntar antes de buscar en internet si la acción implica salir del entorno local.
- Separar claramente conocimiento local de información buscada online.
- Mostrar fuentes/enlaces usados para responder.
- Resumir resultados sin inventar.
- Permitir preguntas como:
  - “¿Cuándo sale Forza Horizon 6?”
  - “Busca documentación de X.”
  - “Qué ha pasado hoy con Y.”
- Definir política de permisos:
  - búsqueda puntual con confirmación
  - dominios permitidos/opcionales
  - bloqueo de webs sensibles si hace falta
- Cachear búsquedas recientes para ahorrar llamadas.

### Google Integration

Pendiente:

- OAuth local.
- Google Drive read-only.
- Gmail read-only.
- Google Calendar read-only.
- Confirmación para acciones sensibles:
  - enviar email
  - borrar email
  - mover archivos
  - crear/modificar eventos
- Separar scopes por capacidad.
- Guardar tokens fuera de Git.
- Revocación/rotación de credenciales.
- Mostrar claramente cuándo Sity está consultando Google.

### Música / Spotify

Pendiente:

- Integración con Spotify.
- Explorar dos rutas:
  - Spotify Web en Vivaldi.
  - Raspotify como Spotify Connect en Raspberry.
- Permitir acciones como:
  - “pon música”
  - “pon mi playlist X”
  - “pausa”
  - “siguiente canción”
  - “qué está sonando”
- Leer gustos/playlists si se usa API de Spotify.
- Pedir permiso antes de enlazar cuentas o controlar reproducción.
- No romper el pipeline custom de audio HDMI.

### IA / Modelos

Pendiente:

- Fallback a futuros modelos.
- Mejor routing entre modelo barato/caro.
- Compresión de contexto.
- Resumen automático de memoria.
- Control más fino del coste de tokens.
- Modo offline/local en el futuro si hay modelo viable.
- Separar mejor planner, conversación y ejecución.
- Evitar llamadas a IA en casos claramente locales.

### Frontend

Pendiente:

- Vista de acciones pendientes.
- Botones de confirmar/cancelar acción.
- Panel de servicios permitidos.
- Panel de estado de sistema.
- Panel de logs/debug.
- Mejor visualización de tokens.
- Mejor edición de personalidad.
- Mejor UX móvil/RasPad.
- Scroll automático robusto al último mensaje.
- Mostrar errores de red/API de forma clara.
- Mostrar si una respuesta vino de Claude o de fast path local.

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

No debe convertirse en una shell con cara amable ni en una IA que ejecuta cosas sin explicar.

La regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar solo si se confirma.
```

Para acciones críticas:

```text
Primero plan.
Luego confirmación.
Después ejecución.
```

Para capacidades externas:

```text
Primero permiso.
Luego consulta.
Después respuesta con trazabilidad.
```
