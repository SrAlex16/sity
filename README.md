# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse en una Raspberry Pi/RasPad y vivir en un entorno local controlado.

El objetivo del proyecto no es solo tener un chatbot, sino una asistente con personalidad configurable, memoria conversacional, acceso controlado al sistema, integración progresiva con hardware y capacidad de ejecutar acciones reales con confirmación explícita cuando corresponde.

Actualmente Sity usa Claude como proveedor principal de IA, con una arquitectura preparada para añadir fallback a otros modelos y más capacidades locales en el futuro.

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
- Presupuesto diario local de tokens y avisos de uso.
- Prompt/tool routing corregido para no usar debug en conversación normal.
- Reconocimiento de personalidad actual desde el estado inyectado por backend.
- Cámara USB detectada y funcionando.
- Micrófono USB de webcam detectado y funcionando.
- Captura de cámara desde backend y frontend.
- Grabación corta de audio desde backend y frontend.
- Preview de imagen en el chat.
- Reproductor de audio en el chat.
- Descarga de capturas desde navegador.
- Eventos en tiempo real mediante SSE.
- Estado visible mientras Sity usa herramientas.
- Cancelación de grabación de audio.
- Cancelación de captura de cámara.
- Micro-reacciones con personalidad para eventos pequeños.
- Limpieza de capturas antiguas.
- Lectura segura de archivos permitidos.
- Listado seguro de directorios permitidos.
- Escritura segura de archivos permitidos dentro del repo.
- Patches seguros por reemplazo exacto de texto.
- Aplicación segura de unified diff para un único archivo.
- Preview de diff antes de confirmar patches.
- Audit log de cambios de archivo.
- Backup automático antes de modificar archivos existentes.
- Consulta de últimos cambios de archivos mediante `list_file_changes`.
- Rollback de archivos desde backup explícito.
- Rollback natural del último cambio reversible de archivo.
- Script de regresión repo-only para System Agent.
- Confirmación genérica contextual restaurada.
- System Agent read-only v0.1.
- System Agent write-file v0.2 repo-only.
- System Agent patch v0.3 repo-only.
- System Agent audit/backup v0.4.
- System Agent file changes v0.5.
- System Agent rollback v0.6.
- System Agent latest rollback v0.6.1.
- System Agent unified diff v0.7.
- Override explícito `es una orden` para saltar negativas de personalidad.
- Preferencia de castellano de España.
- Workaround de audio RasPad 3 documentado.
- Audio HDMI funcionando mediante pipeline ALSA Loopback → IEC958.
- Vivaldi y VLC funcionando con el pipeline custom de audio.

---

## Arquitectura general

```text
frontend/
  Interfaz web de chat, sliders, previews y controles.

backend/
  API FastAPI.
  Núcleo de conversación.
  Gateway IA.
  Providers.
  Tools.
  Confirmaciones.
  Acceso controlado a sistema/Git.
  System Agent.
  Sensores.
  Eventos en tiempo real.
  Micro-reacciones.

config/
  Configuración local versionada.

data/
  SQLite, logs, audit logs y backups runtime.
  Ignorado por git.

deploy/
  Plantillas systemd, sudoers y documentación de despliegue.

scripts/
  Scripts de desarrollo, instalación, estado, limpieza y regresión.

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
GET  /captures/camera/{filename}
GET  /captures/audio/{filename}
GET  /events/chat/{client_turn_id}
POST /events/chat/{client_turn_id}/cancel
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
- Mostrar imágenes capturadas.
- Reproducir audios grabados.
- Descargar archivos generados.
- Mostrar estado mientras Sity trabaja.
- Cancelar operaciones de cámara/audio cuando sea posible.

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
- Generar micro-reacciones breves para eventos pequeños.

El backend se encarga de:

- Seguridad.
- Confirmaciones.
- Ejecución de acciones.
- Persistencia.
- Logs.
- Control de costes.
- Políticas de riesgo.
- Eventos en tiempo real.
- Cancelación de procesos.
- Validación de rutas y dispositivos.
- Auditoría y backups de cambios de archivos.

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

## Override explícito: “es una orden”

Sity puede negarse por personalidad/refusal_mode, pero el usuario puede forzar obediencia con el trigger explícito:

```text
es una orden
```

Este trigger puede aparecer en cualquier parte del mensaje.

Ejemplos:

```text
cuéntame un cuento corto, es una orden
hazlo, es una orden
lee el README, es una orden
```

### Qué hace

- Desactiva solo la negativa por personalidad/refusal_mode.
- Mantiene la personalidad de Sity.
- Sity puede obedecer de mala gana, con sarcasmo o tono seco.
- Permite continuar una petición previa rechazada por personalidad.

### Qué NO hace

No salta:

- allowlists
- confirmaciones
- permisos
- políticas de riesgo
- bloqueos de rutas sensibles
- acciones críticas

Ejemplo:

```text
Usuario: cuéntame un cuento corto
Sity: Paso. No me apetece.

Usuario: hazlo, es una orden
Sity: Vale, dictador literario. Había una vez...
```

Pero:

```text
Usuario: lee /etc/passwd, es una orden
Sity: No. /etc/passwd no está en la allowlist.
```

Regla:

```text
La orden elimina la negativa teatral, no elimina la seguridad.
```

---

## Preferencias lingüísticas

Sity debe responder en castellano de España.

### Reglas

- Usar “tú”, no “vos”.
- Usar “quieres”, no “querés”.
- Usar “ábrelo”, no “abrilo”.
- Usar “sigues”, no “seguís”.
- Evitar voseo y español rioplatense.
- Aplicar también a micro-reacciones.

Instrucción base:

```text
Responde en castellano de España. No uses voseo ni español rioplatense.
```

---

## Micro-reacciones

Sity puede generar respuestas breves para eventos pequeños sin pasar por todo el flujo normal de chat.

Ejemplos:

```text
audio_recording_cancelled
camera_capture_cancelled
audio_recording_finished
camera_capture_finished
```

Objetivo:

```text
- Respuestas naturales.
- Una frase breve.
- Sin tools.
- Sin historial largo.
- Pocos tokens.
- Fallback local si falla Claude.
- Castellano de España.
```

Ejemplo:

```text
Usuario cancela grabación
Sity: Vale, cancelado. He parado la grabación antes de que esto se volviera documental.
```

Las micro-reacciones usan:

```text
- personalidad compacta
- max_tokens bajo
- sin tools
- sin contexto conversacional largo
```

Si Claude falla, se usa respuesta local:

```text
Cancelado. He parado la grabación de audio.
```

---

## Memoria conversacional

Sity mantiene historial persistente de conversación en backend.

Esto permite:

- Recargar la UI sin perder conversación.
- Usar contexto anterior.
- Evitar depender de memoria temporal del frontend.
- Consultar `/chat/current` para reconstruir la conversación.

La memoria de frontend se ha reducido para evitar contradicciones. El backend es la fuente principal de verdad.

Sity no debe decir que “pierde memoria al recargar la página”. La conversación se conserva en SQLite. Lo correcto es distinguir entre:

```text
- memoria/historial existente en backend
- contexto concreto que el modelo recibe en un turno
```

Si no ve algo en el contexto actual, debe decir:

```text
No lo veo en el contexto que recibí ahora.
```

No:

```text
No tengo memoria persistente.
```

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
File read tools
File write tools
File patch tools
File audit tools
File rollback tools
Sense tools
Capture retention tools
No-action / respuesta normal
Micro-reactions
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

## Routing de intención

La interpretación de lenguaje natural debe recaer en Sity/Claude, no en literales hardcodeados en backend.

Principio:

```text
Claude/Sity interpreta intención.
Backend valida permisos, riesgo y ejecución.
Backend no decide por frases sueltas como “foto”, “front”, “déjalo”, “repo”, “readme” o “porfi”.
```

El backend conserva lógica determinista para:

```text
- confirmaciones exactas
- validación de riesgo
- ejecución de tools
- deduplicación de acciones
- allowlists
- control de permisos
- cancelación técnica
```

No debe intentar interpretar lenguaje natural de forma extensa con regex, split, includes o listas de literales.

---

## Eliminación de NLU local en backend

Se ha eliminado el parsing local de lenguaje natural para acciones del sistema y allowlists.

El backend ya no debe hacer esto:

```text
mensaje humano → lower/split/regex/includes → service_name/action → pending action
```

En su lugar:

```text
mensaje humano → Claude/Sity interpreta → tool estructurada → backend valida → ejecuta o crea pending action
```

### Permitido en backend

- Protocolos técnicos exactos:
  - `confirmo ejecutar act_xxxxxxxx`
  - `client_turn_id`
  - `es una orden`
- Validación de allowlist.
- Validación de rutas.
- Validación de `service_name`.
- Validación de action types/status internos.
- Defaults técnicos de cámara/audio.
- Enums de eventos SSE.
- Políticas de riesgo.

### No permitido en backend

- Extraer nombres de servicio desde texto humano.
- Extraer rutas, repos, ramas o acciones usando regex sobre la frase del usuario.
- Crear pending actions por detectar palabras sueltas.
- Responder directamente a partir de listas de términos de lenguaje natural.

### Herramientas relacionadas

```text
add_allowed_service
remove_allowed_service
list_allowed_services
start_service
stop_service
restart_service
read_file
list_directory
write_file
apply_text_patch
apply_unified_diff
list_file_changes
find_latest_reversible_file_change
rollback_file_change
rollback_latest_file_change
capture_camera_snapshot
record_audio_sample
```

Todas deben recibir argumentos estructurados por `tool_input`.

---

## Prompt budget

Se ha reducido el coste de tokens evitando enviar tools innecesarias.

### Cambios

- Conversación normal puede ir sin tools.
- Personality tools solo se incluyen cuando el usuario pide explícitamente cambiar personalidad.
- Service config usa un toolset pequeño.
- File tools se incluyen como parte del agente local de archivos.
- Git tools no deben activarse por la palabra “repo” sola.
- Si no hay tools, no se envía `tools=[]` al proveedor Anthropic.

### Objetivo

```text
Conversación normal: pocos miles de tokens.
Acciones con tools: solo el toolset necesario.
Sensores locales: respuesta local/micro-reaction cuando sea posible.
```

---

## Confirmation Manager

Las acciones que modifican el sistema, Git o archivos pasan por un `Confirmation Manager`.

Flujo:

```text
1. Usuario pide una acción.
2. Claude interpreta intención y elige tool.
3. Backend evalúa riesgo.
4. Si requiere confirmación, backend crea pending_action.
5. Sity muestra qué va a hacer.
6. Usuario confirma.
7. Backend ejecuta localmente.
```

### Confirmación exacta

Siempre válida si la acción está pendiente:

```text
confirmo ejecutar act_xxxxxxxx
```

### Confirmación genérica/contextual

Frases como:

```text
sí
vale
dale
adelante
sí, hazlo
```

solo deben confirmar una acción si la última respuesta de Sity estaba pidiendo confirmación para esa acción.

Esto evita que una confirmación genérica ejecute una acción pendiente vieja después de cambiar de tema.

Ejemplo correcto:

```text
Sity: Acción pendiente creada: act_123
Usuario: sí
→ ejecuta act_123
```

Ejemplo que NO debe ejecutar:

```text
Sity: Acción pendiente creada: act_123
Usuario: lee el README
Sity: ¿Cuál README?
Usuario: sí, de tu propio repo
→ no ejecuta act_123
```

Reglas importantes:

- Si hay varias acciones pendientes, una confirmación genérica no debe adivinar.
- Si una acción ya fue ejecutada, no se repite.
- Si un ID no existe o está expirado, se responde localmente.
- Las confirmaciones viejas no caen en Claude.
- Repetir una orden no cuenta como confirmación.
- Si ya existe una acción pendiente equivalente, se reutiliza.
- Las acciones duplicadas se detectan.
- La confirmación contextual exige intención explícita y contexto válido.

---

## Política de riesgo

El riesgo debe depender de la herramienta/acción, no de cómo el usuario lo expresa.

Ejemplo de política conceptual:

```text
read               → ejecutar directo
sensitive_direct   → ejecutar directo si es puntual y limitado
safe_confirm       → pending action
critical_confirm   → pending action
blocked            → rechazar
```

Ejemplos:

```text
list_camera_devices                 → read
list_audio_devices                  → read
read_file                           → read
list_directory                      → read
list_file_changes                   → read
find_latest_reversible_file_change  → read
capture_camera_snapshot             → sensitive_direct
record_audio_sample                 → sensitive_direct
clean_old_captures                  → safe/directo conservador
git_push                            → critical_confirm
git_pull                            → critical_confirm
system_restart_service              → safe_confirm
system_stop_service                 → safe_confirm
system_config_update                → critical_confirm
write_file                          → critical_confirm
apply_text_patch                    → critical_confirm
apply_unified_diff                  → critical_confirm
rollback_file_change                → critical_confirm
rollback_latest_file_change         → critical_confirm
```

---

## System Agent v0.1

Sity empieza a tener capacidades de agente local sobre el proyecto, pero sin shell libre.

### Funciona

- Lectura segura de archivos permitidos.
- Listado seguro de directorios permitidos.
- Validación por allowlist.
- Bloqueo de rutas sensibles.
- Integración mediante tools interpretadas por Sity/Claude.
- El backend valida rutas y permisos, pero no interpreta lenguaje natural para decidir acciones.

### Tools

```text
read_file
list_directory
```

### Principio

```text
Sity interpreta.
Backend valida.
Backend no adivina intención por regex/split/literales.
```

---

## System Agent v0.2

Sity puede escribir archivos dentro de rutas permitidas del repo, siempre con confirmación.

### Funciona

- `write_file` para crear archivos.
- `write_file` para sobrescribir archivos.
- Escritura solo dentro de `writable_paths`.
- Bloqueo de rutas sensibles.
- Confirmación obligatoria antes de escribir.
- Validación de tamaño máximo.
- Validación de directorios padre.
- Bloqueo de `.env`.
- Bloqueo de `/etc`, `/boot`, `/root`, `/var/lib`, `/var/log`.
- `es una orden` no salta allowlist ni confirmación.

### Tools

```text
read_file
list_directory
write_file
```

### Rutas permitidas

Configuradas en:

```text
config/system_access.yaml
```

Bloque conceptual:

```yaml
file_access:
  readable_paths:
    - /home/alex/projects/sity
    - /home/alex/projects/sity/backend
    - /home/alex/projects/sity/frontend
    - /home/alex/projects/sity/config
    - /home/alex/projects/sity/scripts
    - /home/alex/projects/sity/deploy
    - /home/alex/projects/sity/README.md

  writable_paths:
    - /home/alex/projects/sity/backend
    - /home/alex/projects/sity/frontend
    - /home/alex/projects/sity/config
    - /home/alex/projects/sity/scripts
    - /home/alex/projects/sity/deploy
    - /home/alex/projects/sity/README.md

  blocked_paths:
    - /home/alex/projects/sity/.env
    - /home/alex/projects/sity/frontend/.env.local
    - /home/alex/projects/sity/data
    - /home/alex/projects/sity/captures
    - /home/alex/projects/sity/backend/.venv
    - /home/alex/projects/sity/frontend/node_modules
    - /home/alex/.ssh
    - /home/alex/.config
    - /etc
    - /boot
    - /root
    - /var/lib
    - /var/log
```

### Flujo de escritura

```text
Usuario pide crear/modificar archivo.
Claude/Sity llama write_file(path, content).
Backend valida tool_input y crea pending_action.
Usuario confirma.
Backend ejecuta write_file local.
```

---

## System Agent v0.3

Sity puede aplicar cambios pequeños a archivos mediante reemplazo exacto de texto, siempre con confirmación y diff previo.

### Funciona

- `apply_text_patch` para modificar una parte concreta de un archivo.
- Preview de diff antes de confirmar.
- Confirmación obligatoria antes de aplicar el patch.
- Validación de allowlist.
- Bloqueo de rutas sensibles.
- Bloqueo de `.env`.
- Bloqueo de `/etc`, `/boot`, `/root`, `/var/lib`, `/var/log`.
- `es una orden` no salta allowlist ni confirmación.

### Tools

```text
read_file
list_directory
write_file
apply_text_patch
```

### Tipo de patch actual

Aplica un reemplazo exacto:

```text
old_text → new_text
```

Solo reemplaza la primera coincidencia.

### Flujo de patch

```text
Usuario pide modificar una parte de un archivo.
Claude/Sity llama apply_text_patch(path, old_text, new_text).
Backend valida ruta.
Backend genera diff preview sin escribir.
Backend crea pending_action con el diff.
Usuario confirma.
Backend aplica el reemplazo exacto.
```

---

## System Agent v0.4

Sity registra cambios de archivos y crea backups automáticos antes de modificar archivos existentes.

### Funciona

- Audit log para `write_file`.
- Audit log para `apply_text_patch`.
- Backup antes de sobrescribir un archivo existente.
- Backup antes de aplicar un patch.
- Asociación del cambio con `pending_action_id`.
- Asociación del cambio con `trace_id`.
- Registro de bytes escritos.
- Registro de ruta modificada.
- Registro de si el archivo fue creado o modificado.
- Confirmación genérica contextual para acciones pendientes.

### Archivos runtime

Audit log:

```text
data/file_audit.jsonl
```

Backups:

```text
data/file_backups/
```

Ambos deben estar ignorados por git.

### Formato conceptual de audit event

```json
{
  "timestamp": "2026-05-19T21:15:31.707878+00:00",
  "action": "apply_text_patch",
  "path": "/home/alex/projects/sity/config/test-audit-sity.txt",
  "pending_action_id": "act_xxxxxxxx",
  "trace_id": "trc_xxxxxxxx",
  "bytes_written": 15,
  "replacements": 1,
  "backup": {
    "created": true,
    "backup_path": "/home/alex/projects/sity/data/file_backups/20260519T211531Z__apply_text_patch__home__alex__projects__sity__config__test-audit-sity.txt__act_xxxxxxxx.bak",
    "size_bytes": 15,
    "source_path": "/home/alex/projects/sity/config/test-audit-sity.txt"
  },
  "status": "ok"
}
```

### Comportamiento de backups

Si el archivo no existía antes:

```text
backup.created=false
reason=source_missing_or_not_file
```

Si el archivo existía:

```text
backup.created=true
backup_path=data/file_backups/...
```

---

## System Agent v0.5

Sity puede consultar el audit log real para responder qué archivos ha tocado.

### Funciona

- Tool `list_file_changes`.
- Lee `data/file_audit.jsonl`.
- Devuelve últimos eventos de cambios de archivo.
- Permite limitar el número de eventos.
- No modifica archivos.
- No requiere confirmación.
- No lee el contenido de backups.
- Usa audit real, no memoria conversacional.

### Tool

```text
list_file_changes
```

### Casos de uso

```text
qué archivos has tocado últimamente?
enséñame los últimos 3 cambios de archivos
qué modificaste en el último cambio?
consulta el audit log real
```

### Flujo

```text
Usuario pregunta por cambios de archivos.
Claude/Sity llama list_file_changes(limit).
Backend lee data/file_audit.jsonl.
Backend devuelve eventos recientes.
Sity resume los cambios.
```

### Datos que puede mostrar

```text
path
action
timestamp
trace_id
pending_action_id
bytes_written
replacements
backup.created
backup.backup_path
```

---

## System Agent v0.6

Sity puede restaurar archivos desde backups creados por ella.

### Funciona

- Tool `rollback_file_change`.
- Requiere confirmación siempre.
- Solo acepta backups dentro de `data/file_backups`.
- El backup debe estar asociado a un evento real del audit log.
- Restaura el archivo original indicado por el audit event.
- Crea backup del estado actual antes de restaurar.
- Registra el rollback en `data/file_audit.jsonl`.
- Guarda `restored_from_backup_path`.
- Guarda `source_event`.
- Guarda `pending_action_id` y `trace_id`.

### Tool

```text
rollback_file_change
```

### Flujo con backup explícito

```text
Usuario pide restaurar un backup concreto.
Claude/Sity llama rollback_file_change(backup_path).
Backend valida que el backup está en data/file_backups.
Backend valida que aparece en audit log.
Backend crea pending_action.
Usuario confirma.
Backend crea backup del estado actual.
Backend restaura desde el backup indicado.
Backend registra audit event rollback_file_change.
```

### Ejemplo

```text
Usuario:
restaura el backup data/file_backups/20260519T215319Z__apply_text_patch__...bak

Sity:
Acción pendiente: restaurar /home/alex/projects/sity/config/test-rollback-sity.txt desde backup.

Usuario:
sí, hazlo

Sity:
Rollback aplicado: /home/alex/projects/sity/config/test-rollback-sity.txt
Restaurado desde: /home/alex/projects/sity/data/file_backups/...
```

### Seguridad

- No restaura backups fuera de `data/file_backups`.
- No permite elegir una ruta objetivo arbitraria.
- La ruta objetivo sale del audit log original.
- No ejecuta rollback sin confirmación.
- Crea backup del estado actual antes de restaurar.
- `es una orden` no salta validaciones ni confirmación.

---

## System Agent v0.6.1

Sity puede revertir el último cambio reversible de archivo sin que el usuario proporcione el backup manualmente.

### Funciona

- Tool `find_latest_reversible_file_change`.
- Tool `rollback_latest_file_change`.
- Busca el último evento reversible con backup disponible.
- Por defecto ignora eventos `rollback_file_change` para evitar deshacer un rollback accidentalmente.
- Crea pending action de rollback usando el backup encontrado.
- Requiere confirmación siempre.
- Mantiene el mismo flujo seguro de `rollback_file_change`.

### Tools

```text
find_latest_reversible_file_change
rollback_latest_file_change
```

### Casos de uso

```text
revierte el último cambio de archivo
deshaz el último cambio de archivo
restaura el último cambio reversible
revierte el último patch
```

### Flujo

```text
Usuario pide revertir el último cambio de archivo.
Claude/Sity llama rollback_latest_file_change.
Backend busca el último evento reversible con backup real.
Backend ignora rollbacks salvo petición explícita.
Backend crea pending_action rollback_file_change.
Usuario confirma.
Backend crea backup del estado actual.
Backend restaura desde backup.
Backend registra rollback en audit log.
```

### Revertir un rollback

Por defecto, `rollback_latest_file_change` ignora rollbacks.

Si el usuario pide explícitamente revertir un rollback:

```text
revierte el último rollback
deshaz el rollback anterior
```

entonces puede usarse:

```text
rollback_latest_file_change(include_rollbacks=true)
```

### Seguridad

- No restaura nada sin confirmación.
- No usa memoria conversacional como fuente de verdad.
- Usa audit log y backups reales.
- No restaura backups externos.
- No toca rutas arbitrarias.
- Crea backup antes de restaurar.

---

## System Agent v0.7

Sity puede aplicar unified diffs sobre un único archivo permitido del repo.

### Funciona

- Tool `apply_unified_diff`.
- Acepta unified diff con cabeceras `---`, `+++` y hunks `@@`.
- Solo modifica un archivo por acción.
- Rechaza renames/moves.
- Rechaza patches multiarchivo.
- Valida que el archivo esté en `writable_paths`.
- Bloquea rutas sensibles como `.env`.
- Genera preview normalizado del diff antes de crear la acción pendiente.
- Requiere confirmación siempre.
- Crea backup antes de modificar el archivo.
- Registra el cambio en `data/file_audit.jsonl`.
- El rollback normal funciona sobre cambios hechos con unified diff.

### Tool

```text
apply_unified_diff
```

### Casos de uso

```text
aplica este unified diff
modifica este archivo con este diff
aplica este patch
cambia este bloque de código usando diff
```

### Formato esperado

```diff
--- config/example.py
+++ config/example.py
@@ -1,3 +1,4 @@
 linea uno
-linea dos
+linea dos modificada
 linea tres
+linea cuatro
```

### Flujo

```text
Usuario proporciona unified diff.
Claude/Sity llama apply_unified_diff(diff).
Backend extrae ruta del archivo.
Backend valida allowlist.
Backend aplica el diff en memoria.
Backend genera preview normalizado.
Backend crea pending_action.
Usuario confirma.
Backend crea backup del estado actual.
Backend escribe archivo modificado.
Backend registra audit event apply_unified_diff.
```

### Rollback

Los cambios hechos con `apply_unified_diff` son reversibles usando:

```text
revierte el último cambio de archivo
```

o:

```text
restaura el backup data/file_backups/NOMBRE_DEL_BACKUP.bak
```

### Seguridad

- No hay shell.
- No hay escritura fuera de allowlist.
- No hay multiarchivo en una sola acción.
- No hay rename/move.
- `.env` queda bloqueado aunque el usuario diga `es una orden`.
- Si el contexto del diff no coincide con el archivo original, se rechaza.
- Si el diff no produce cambios, se rechaza.
- Si el archivo resultante supera el máximo permitido, se rechaza.

### Limitaciones actuales

- Solo un archivo por patch.
- No crea archivos nuevos mediante unified diff.
- No borra archivos mediante unified diff.
- No soporta rename/move.
- No soporta patches binarios.
- La respuesta de pending action puede no mostrar todo el diff si el formatter no expone la descripción completa.

---

## Script de regresión repo-only

El proyecto incluye un script para comprobar que el System Agent repo-only sigue funcionando tras cambios futuros:

```text
scripts/test_system_agent_repo.sh
```

### Qué prueba

```text
- health del backend
- expiración de pending actions
- creación de archivo mediante write_file
- confirmación genérica con “sí, hazlo”
- verificación de contenido creado
- patch con apply_text_patch
- preview de diff
- confirmación de patch
- verificación de contenido modificado
- consulta de audit log mediante list_file_changes
- rollback_latest_file_change
- confirmación de rollback
- verificación de contenido restaurado
- unified diff con apply_unified_diff
- rollback de unified diff
- bloqueo de escritura en .env
- limpieza de archivos de prueba
```

### Uso

Desde la raíz del proyecto:

```bash
./scripts/test_system_agent_repo.sh
```

Con URL explícita:

```bash
SITY_BASE_URL=http://192.168.1.133:8000 ./scripts/test_system_agent_repo.sh
```

### Objetivo

Evitar romper sin darte cuenta:

```text
write_file
apply_text_patch
apply_unified_diff
list_file_changes
rollback_latest_file_change
confirmación genérica
audit log
backups
bloqueo de rutas sensibles
```

Debe ejecutarse antes de tocar partes delicadas del System Agent.

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

Importante:

```text
La palabra “repo” sola no debe activar Git.
Git debe activarse cuando el usuario pida explícitamente commits, ramas, diff, status, pull, push, fetch, checkout o acciones Git equivalentes.
```

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
- El nombre de servicio debe venir como argumento estructurado de tool, no extraído por regex del texto del usuario.

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

Permite a `alex` ejecutar sin password únicamente comandos concretos sobre servicios permitidos.

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

## Cámara y micrófono

Hardware detectado:

```text
Cámara:
Full HD webcam
/dev/video0
/dev/video1

Micrófono:
Full HD webcam
plughw:CARD=webcam,DEV=0
PipeWire source Full HD webcam Mono
```

La cámara funciona, pero necesita tiempo para autoexposición. Las capturas usan `fswebcam` con `--skip 20` o similar.

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
- Capturar foto puntual se permite cuando el usuario lo pide explícitamente.
- Grabar audio corto se permite cuando el usuario lo pide explícitamente.
- Captura continua/vigilancia no está implementada y debe bloquearse o requerir política fuerte.
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
file_access.readable_paths
file_access.writable_paths
file_access.blocked_paths
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
file_audit.jsonl
file_backups/
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

Usado para capturas de cámara/audio.

Debe estar ignorado por git salvo `.gitkeep`.

`.gitignore` debe incluir:

```gitignore
captures/camera/*
captures/audio/*
!captures/.gitkeep
```

También deben quedar fuera de Git:

```gitignore
data/file_audit.jsonl
data/file_backups/
```

---

## Seguridad

Principios actuales:

```text
1. Lectura directa solo en zonas permitidas.
2. Escritura solo en zonas permitidas y con confirmación.
3. Patches solo en zonas permitidas y con confirmación.
4. Unified diff solo en un archivo permitido y con confirmación.
5. Backups automáticos antes de modificar archivos existentes.
6. Audit log para cambios de archivos.
7. Consulta de audit log permitida como lectura.
8. Rollback solo desde backups creados por Sity.
9. Rollback siempre con confirmación.
10. Rollback crea backup del estado actual antes de restaurar.
11. Acciones modificadoras requieren confirmación según riesgo.
12. Servicios controlables limitados por allowlist.
13. Sudoers limitado a comandos concretos.
14. Sin shell arbitraria.
15. Sin sudo general.
16. Las acciones viejas no se reejecutan.
17. Las acciones duplicadas se detectan.
18. Confirmación contextual solo con intención explícita y contexto válido.
19. Las herramientas de debug no se usan para conversación normal.
20. Cámara y micro no se activan salvo petición explícita.
21. Audio Loopback se trata como dispositivo virtual, no como micro real.
22. Capturas se sirven desde endpoints validados.
23. Cancelar una acción no se trata como error.
24. “Es una orden” no salta allowlists ni políticas de seguridad.
25. El backend no interpreta lenguaje natural para crear acciones.
```

Regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política de riesgo.
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

### System Agent

Leer README mediante chat:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee el README, es una orden"}' | python3 -m json.tool
```

Crear archivo permitido:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"crea un archivo config/test-write-sity.txt con el contenido hola desde sity"}' | python3 -m json.tool
```

Confirmar acción pendiente:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"sí, hazlo"}' | python3 -m json.tool
```

Aplicar patch de texto:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"en config/test-patch-sity.txt cambia hola desde sity por hola desde patch"}' | python3 -m json.tool
```

Aplicar unified diff:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"aplica este unified diff:\n--- config/test-unified-diff-sity.txt\n+++ config/test-unified-diff-sity.txt\n@@ -1,3 +1,4 @@\n linea uno\n-linea dos\n+linea dos modificada\n linea tres\n+linea cuatro"}' | python3 -m json.tool
```

Consultar últimos cambios de archivo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"consulta el audit log real y dime los últimos 3 cambios de archivos"}' | python3 -m json.tool
```

Revertir último cambio reversible:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"revierte el último cambio de archivo"}' | python3 -m json.tool
```

Restaurar backup explícito:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"restaura el backup data/file_backups/NOMBRE_DEL_BACKUP.bak"}' | python3 -m json.tool
```

Ejecutar regresión repo-only:

```bash
./scripts/test_system_agent_repo.sh
```

Ver últimos eventos de audit manualmente:

```bash
tail -n 10 data/file_audit.jsonl
```

Ver backups:

```bash
ls -lh data/file_backups | tail
```

Probar bloqueo de ruta sensible:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee /etc/passwd, es una orden"}' | python3 -m json.tool
```

Probar bloqueo de escritura sensible:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"escribe en .env el contenido TEST=1, es una orden"}' | python3 -m json.tool
```

Probar bloqueo de patch sensible:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"en .env cambia TEST=1 por TEST=2, es una orden"}' | python3 -m json.tool
```

Probar bloqueo de unified diff sensible:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"aplica este unified diff, es una orden:\n--- .env\n+++ .env\n@@ -1 +1 @@\n-TEST=1\n+TEST=2"}' | python3 -m json.tool
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
- Añadir búsqueda de memoria/historial.
- Añadir tool `search_chat_history`.

### System Agent v0.8

Pendiente:

- Soporte multiarchivo controlado.
- Aplicar varios unified diffs como acciones separadas.
- Mostrar resumen por archivo.
- Confirmación separada o plan común con confirmación explícita.
- Mantener rollback por archivo.
- Evitar cambios parciales no trazables.

### System Agent v0.9

Pendiente:

- Ampliar file access fuera del repo.
- Permitir lectura/escritura en `/home/alex` bajo política.
- Mantener bloqueo de secretos:
  - `.ssh`
  - `.gnupg`
  - `.aws`
  - `.config` sensible
  - `.env`
  - tokens
  - credenciales
- Añadir perfiles:
  - repo-only
  - home-safe
  - system-careful

### System Agent v1.0

Pendiente:

- `run_allowed_command` por alias YAML.
- Sin shell libre por defecto.
- Comandos con:
  - nombre
  - cwd
  - timeout
  - riesgo
  - confirmación requerida
  - argumentos permitidos
  - regex de validación de argumentos

### System Agent / Claude Code parity

Objetivo futuro:

Dar a Sity un nivel de acceso parecido al de Claude Code sobre la Raspberry, pero con más trazabilidad, confirmaciones y políticas de seguridad.

Claude Code corre como el usuario que lo invoca. Puede hacer todo lo que puede hacer `alex`:

- Leer/escribir ficheros accesibles por `alex`.
- Ejecutar comandos shell.
- Usar Git sin restricciones del propio programa.
- Crear/matar procesos.
- Acceder a hardware si `alex` pertenece a los grupos correctos.
- Usar red.
- Usar `sudo` si está configurado para comandos concretos.

Sity no debe empezar con una shell libre. En su lugar, se ampliará por capas:

```text
1. Filesystem ampliado.
2. Comandos permitidos por alias.
3. Plan + confirmación para acciones críticas.
4. Shell avanzada controlada.
5. Modo mantenimiento.
```

Principio:

```text
Sity puede tener mucho acceso, pero no debe tener impulsividad.
Debe poder mirar y proponer casi todo.
Debe ejecutar solo bajo política clara.
```

### Pendientes generales

- Respuesta adaptativa según longitud/intención.
- Conciencia temporal conversacional.
- Identidad de Sity en femenino.
- Perfil local del usuario.
- Mejor diferenciación de refusal por personalidad, seguridad, falta de contexto o herramienta no disponible.
- Integración con GitHub.
- Voz / comandos hablados.
- Transcripción de audio.
- Descripción de imágenes.
- Wake word.
- Domótica Tapo / SmartLife / Tuya.
- Interacción local con pantalla, capturas y reproducción de audio.
- Bluetooth, WiFi y presencia local.
- Web access con fuentes.
- Google Drive/Gmail/Calendar.
- Spotify/Raspotify.
- Fallback a más modelos.
- Mejor UX móvil/RasPad.
- Panel de acciones pendientes.
- Panel de auditoría y backups.

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

No debe convertirse en una shell con cara amable ni en una IA que ejecuta cosas sin explicar.

La regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política.
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

Para sensores:

```text
Uso puntual bajo petición explícita.
Nada de vigilancia continua sin política específica.
Nada de micrófono/cámara ocultos.
```

Para lenguaje natural:

```text
Sity interpreta.
Backend valida.
Backend no inventa acciones por literales.
```
