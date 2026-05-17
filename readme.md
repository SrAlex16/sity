# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse en una Raspberry Pi/RasPad y vivir en un entorno local controlado.

El objetivo del proyecto no es solo tener un chatbot, sino una asistente con personalidad configurable, memoria conversacional, acceso controlado al sistema y capacidad de ejecutar acciones reales con confirmación explícita.

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

config/
  Configuración local versionada.

data/
  SQLite, logs y datos runtime.
  Ignorado por git.

deploy/
  Plantillas systemd y sudoers versionadas.

scripts/
  Scripts de desarrollo, instalación y estado.
```

---

## Backend

El backend expone, entre otros:

```text
GET  /health
POST /chat/message
GET  /settings/personality
POST /settings/personality/adjust
```

El endpoint principal es:

```text
POST /chat/message
```

Ejemplo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
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

---

## IA / Claude

Actualmente Sity usa Claude como proveedor principal.

Modelo usado durante el desarrollo:

```text
claude-haiku-4-5-20251001
```

El sistema está planteado para que en el futuro exista fallback a otros modelos, pero ahora mismo el proyecto está centrado en Claude.

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
```

Sity puede leer la configuración actual que el backend le inyecta en el prompt y adaptar su comportamiento a esos valores.

---

## Memoria conversacional

Sity mantiene historial persistente de conversación en backend.

Esto permite:

- Recargar la UI sin perder conversación.
- Usar contexto anterior.
- Evitar depender de memoria temporal del frontend.

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
```

Las tools críticas no se ejecutan directamente. Se crea una acción pendiente y se exige confirmación.

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
```

Esto evita gastar miles de tokens en tareas deterministas.

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

### sity-test

Servicio HTTP mínimo para pruebas.

```text
http://localhost:8099
```

Devuelve:

```text
sity service test
```

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
```

---

## Pendiente / Roadmap

### Core pendiente

- Mejorar manejo de múltiples acciones pendientes.
- Añadir vista/listado de pending actions desde chat.
- Permitir cancelar acciones pendientes desde chat.
- Deduplicar también acciones Git.
- Mejorar mensajes de confirmación para usar nombres humanos en vez de nombres systemd.
- Añadir tests automatizados para confirmation manager.
- Añadir migraciones de base de datos si el esquema crece.

### System Access

- Añadir gestión de allowlist de rutas.
- Añadir lectura segura de archivos permitidos.
- Añadir logs de servicios systemd.
- Añadir health checks por servicio.
- Añadir plantillas para crear nuevos servicios systemd desde planes confirmados.
- Añadir acciones críticas planificadas para instalar/configurar servicios.

### Git

- Prevalidación más inteligente antes de pull/push/commit.
- Proponer stash/commit si el working tree está sucio.
- Crear PRs en GitHub.
- Leer issues y pull requests.
- Integración con GitHub CLI o API.
- Gestión segura de ramas remotas.

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

### IA / Modelos

Pendiente:

- Fallback a futuros modelos.
- Mejor routing entre modelo barato/caro.
- Compresión de contexto.
- Resumen automático de memoria.
- Control más fino del coste de tokens.
- Modo offline/local en el futuro si hay modelo viable.

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

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

La regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar solo si se confirma.
```

Para acciones críticas, primero plan. Luego confirmación. Después ejecución.
