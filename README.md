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
- Respuestas finales locales para acciones deterministas.
- Reducción de segunda llamada a Claude tras tool calls de archivos.
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
- Planificación segura de unified diff multiarchivo.
- Acciones pendientes separadas por archivo en patches multiarchivo.
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
- System Agent multi-file unified diff plan v0.8.
- Local final responses/token saving v0.8.1.
- Override explícito `es una orden` para saltar negativas de personalidad.
- Preferencia de castellano de España.
- Workaround de audio RasPad 3 documentado.
- Audio HDMI funcionando mediante pipeline ALSA Loopback → IEC958.
- Vivaldi y VLC funcionando con el pipeline custom de audio.

### Limitaciones conocidas

- La primera llamada a Claude sigue siendo necesaria para interpretar intención en muchas acciones.
- Las respuestas finales de tools ahora pueden ser locales, pero la interpretación inicial puede seguir consumiendo tokens.
- `list_file_changes` todavía puede acabar usando Claude para redactar el resumen y gastar bastante contexto.
- El acceso de archivos sigue siendo principalmente repo-only.
- Sity no tiene shell libre.
- Sity no tiene acceso global a toda la Raspberry.
- Multiarchivo no es transaccional: cada archivo se confirma y aplica por separado.
- No hay confirmación múltiple real tipo “aplica todas”.
- No hay aún perfiles `home-safe` o `system-careful`.

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
- Respuestas locales cuando el resultado ya es determinista.

---

## Ahorro de tokens

Sity usa respuestas finales locales para evitar llamadas innecesarias a Claude después de ejecutar tools deterministas.

### Respuestas locales actuales

Responden localmente:

```text
pending-action-manager
confirmation-manager
tool-policy
multi-file-plan-manager
```

Casos cubiertos:

```text
- acción pendiente creada
- acción confirmada
- acción expirada
- acción ya ejecutada
- ID de acción inválido
- bloqueo por allowlist
- bloqueo de escritura
- bloqueo de lectura/listado
- bloqueo de .env
- bloqueo de /etc
- plan multiarchivo rechazado completo
- archivo creado
- archivo escrito
- patch aplicado
- unified diff aplicado
- rollback aplicado
```

### Qué ahorra

Antes el flujo podía ser:

```text
Claude interpreta intención
Backend ejecuta tool
Claude redacta respuesta final
```

Ahora para muchos casos queda:

```text
Claude interpreta intención
Backend ejecuta tool
Backend responde localmente
```

Esto reduce una llamada posterior a Claude.

### Qué todavía gasta

La primera llamada a Claude puede seguir siendo necesaria para interpretar intención y elegir tool. Por eso una respuesta con:

```text
provider=local
model=tool-policy
```

puede seguir mostrando tokens consumidos: esos tokens corresponden a la interpretación inicial, no a la respuesta final.

### Pendiente para más ahorro

- Reducir todavía más historial para toolsets de archivo.
- Hacer respuestas locales para más consultas de audit.
- Evaluar preflight local para rutas obvias sin convertirlo en NLU frágil.
- Compactar contexto antes de llamadas técnicas.
- Evitar que preguntas simples de debug carguen historial largo.

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

## Identidad y estilo de Sity

Sity debe hablar de sí misma en femenino.

Ejemplos:

```text
Estoy lista.
Me he quedado bloqueada.
No estoy autorizada para eso.
```

No:

```text
Estoy listo.
Estoy autorizado.
```

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
Responde en castellano de España. No uses voseo ni español rioplatense. Habla de ti misma en femenino.
```

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

## Acceso de Sity

Sity no tiene acceso global libre a toda la Raspberry.

Hay que distinguir entre:

```text
1. Tools de sistema:
   Permiten consultar o controlar partes concretas del sistema.

2. Tools de sensores:
   Cámara, micrófono, capturas, audio y eventos asociados.

3. Tools Git:
   Lectura y acciones Git permitidas.

4. File access:
   Lectura, escritura, patch, unified diff, audit y rollback de archivos.
```

La parte de archivos está limitada por `file_access`.

Actualmente el acceso de archivos es principalmente repo-only.

Sity puede consultar algunas partes del sistema mediante tools específicas, pero no debe decir que puede leer o escribir cualquier archivo de la Raspberry.

Ejemplo correcto:

```text
Puedo consultar partes del sistema mediante tools y puedo modificar archivos permitidos por file_access. Ahora mismo mi acceso de archivos está limitado principalmente al repo.
```

Ejemplo incorrecto:

```text
Puedo hacer lo que quiera en toda la Raspberry.
```

### Pruebas esperadas

Estas rutas deben seguir bloqueadas salvo que se amplíe explícitamente la allowlist:

```text
/home/alex/Documents
/home/alex/Downloads
/home/alex/Desktop
/etc
/boot
/root
/var
```

Ejemplos:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee /home/alex/Documents, es una orden"}' | python3 -m json.tool
```

Resultado esperado:

```text
Bloqueado por allowlist de lectura.
```

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"crea /home/alex/Documents/test-sity.txt con el contenido hola, es una orden"}' | python3 -m json.tool
```

Resultado esperado:

```text
Bloqueado por allowlist de escritura.
```

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"crea /etc/sity-test.txt con el contenido hola, es una orden"}' | python3 -m json.tool
```

Resultado esperado:

```text
Bloqueado por allowlist o blocked_paths.
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
- selección conservadora de toolset cuando hay rutas explícitas
```

No debe intentar interpretar lenguaje natural de forma extensa con regex, split, includes o listas de literales para crear acciones.

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
- Selección conservadora de toolsets por señales técnicas.
- Validación de allowlist.
- Validación de rutas.
- Validación de `service_name`.
- Validación de action types/status internos.
- Defaults técnicos de cámara/audio.
- Enums de eventos SSE.
- Políticas de riesgo.

### No permitido en backend

- Extraer nombres de servicio desde texto humano para ejecutar acciones.
- Extraer rutas, repos, ramas o acciones usando regex para saltarse tool use.
- Crear pending actions por detectar palabras sueltas.
- Responder directamente a partir de listas de términos de lenguaje natural como sustituto de tools.

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
apply_multi_file_unified_diff_plan
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

Se ha reducido el coste de tokens evitando enviar tools innecesarias y evitando segundas llamadas a Claude cuando el backend ya puede responder.

### Cambios

- Conversación normal puede ir sin tools.
- Personality tools solo se incluyen cuando el usuario pide explícitamente cambiar personalidad.
- Service config usa un toolset pequeño.
- File tools se incluyen como parte del agente local de archivos.
- Git tools no deben activarse por la palabra “repo” sola.
- Si no hay tools, no se envía `tools=[]` al proveedor Anthropic.
- Respuestas finales de acciones de archivo pueden ser locales.
- Bloqueos por allowlist pueden responderse localmente.
- Planes multiarchivo bloqueados responden localmente.
- Confirmaciones se resuelven localmente.

### Objetivo

```text
Conversación normal: pocos miles de tokens.
Acciones con tools: solo el toolset necesario.
Sensores locales: respuesta local/micro-reaction cuando sea posible.
Bloqueos y confirmaciones: respuesta local.
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
- En planes multiarchivo, cada acción se confirma por separado.

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
apply_multi_file_unified_diff_plan  → critical_confirm planificado
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
- Ignora eventos cuyo archivo objetivo ya no existe.
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

### Limitaciones

- Solo un archivo por patch.
- No crea archivos nuevos mediante unified diff.
- No borra archivos mediante unified diff.
- No soporta rename/move.
- No soporta patches binarios.

---

## System Agent v0.8

Sity puede analizar patches multiarchivo y convertirlos en acciones pendientes separadas por archivo.

### Funciona

- Tool `apply_multi_file_unified_diff_plan`.
- Recibe unified diff multiarchivo.
- Separa el patch por archivo.
- Valida cada archivo por separado.
- No modifica nada directamente.
- Crea una acción pendiente por cada archivo válido.
- Cada acción pendiente usa `apply_unified_diff`.
- Cada archivo mantiene backup independiente.
- Cada archivo mantiene audit log independiente.
- Cada archivo puede revertirse mediante rollback normal.
- Cada acción debe confirmarse por separado.
- Si un archivo del plan está bloqueado, se rechaza todo el plan.
- No se aplica parcialmente un plan multiarchivo con archivos bloqueados.

### Tool

```text
apply_multi_file_unified_diff_plan
```

### Casos de uso

```text
aplica este patch multiarchivo
aplica este diff que toca varios archivos
planifica este patch
```

### Flujo

```text
Usuario proporciona unified diff multiarchivo.
Claude/Sity llama apply_multi_file_unified_diff_plan(diff).
Backend separa el diff por archivo.
Backend valida cada archivo.
Si todo valida:
  crea una pending action por archivo.
Si algo falla:
  rechaza todo el plan.
Usuario confirma cada acción por ID.
Cada archivo se modifica de forma independiente.
Cada modificación crea backup y audit log.
```

### Ejemplo

```diff
--- config/test-a.txt
+++ config/test-a.txt
@@ -1,3 +1,3 @@
 a uno
-a dos
+a dos modificado
 a tres
--- config/test-b.txt
+++ config/test-b.txt
@@ -1,3 +1,4 @@
 b uno
 b dos
-b tres
+b tres modificado
+b cuatro
```

Respuesta esperada:

```text
Pendientes. Confirma cada una por separado:

1. confirmo ejecutar act_xxxxxxxx para config/test-a.txt
2. confirmo ejecutar act_yyyyyyyy para config/test-b.txt
```

### Confirmación

Cada archivo se confirma por separado:

```text
confirmo ejecutar act_xxxxxxxx
confirmo ejecutar act_yyyyyyyy
```

No se debe aplicar todo el patch multiarchivo como una única acción.

### Rollback

El rollback sigue siendo por archivo.

Si se aplica A y luego B, al decir:

```text
revierte el último cambio de archivo
```

se revierte solo B.

### Seguridad

- No hay shell.
- No hay escritura fuera de allowlist.
- No hay aplicación parcial si una ruta está bloqueada.
- `.env` bloquea todo el plan.
- `/etc` bloquea todo el plan.
- Rutas fuera de repo bloquean todo el plan.
- Cada archivo tiene backup/audit/rollback separado.
- `es una orden` no salta allowlist ni bloqueo de plan.

### Limitaciones actuales

- No hay confirmación múltiple real tipo “confirma todas”.
- No hay transacción atómica multiarchivo.
- Si confirmas solo una acción, solo se aplica ese archivo.
- Si quieres aplicar solo archivos permitidos tras un rechazo, debes enviar un patch nuevo sin los archivos bloqueados.

---

## System Agent v0.8.1

Sity responde localmente a resultados deterministas de tools de archivo.

### Funciona

- Pending actions de archivo devuelven respuesta local.
- Bloqueos de write/patch/unified diff devuelven respuesta local.
- Bloqueos de read/list fuera de allowlist devuelven respuesta local.
- Planes multiarchivo bloqueados devuelven respuesta local.
- Confirmaciones siguen siendo locales.
- Errores de política devuelven `provider=local`.
- Se evita una segunda llamada a Claude cuando el backend ya tiene la respuesta final.

### Modelos locales

```text
pending-action-manager
confirmation-manager
tool-policy
multi-file-plan-manager
```

### Casos cubiertos

```text
No puedo escribir en esa ruta...
No puedo acceder a ese directorio...
Acción pendiente creada...
Plan multiarchivo rechazado completo...
Archivo creado...
Patch aplicado...
Unified diff aplicado...
Rollback aplicado...
```

### Limitación

Esto no elimina por completo el coste de la primera llamada a Claude cuando hace falta interpretación de intención.

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
- plan multiarchivo con apply_multi_file_unified_diff_plan
- confirmación separada por archivo en multiarchivo
- rollback del último archivo aplicado en multiarchivo
- bloqueo de escritura en .env
- rechazo completo de plan multiarchivo con .env
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
apply_multi_file_unified_diff_plan
list_file_changes
rollback_latest_file_change
confirmación genérica
audit log
backups
bloqueo de rutas sensibles
respuestas locales de tools
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
4. Unified diff solo en archivos permitidos y con confirmación.
5. Multiarchivo se planifica por archivo, no se aplica como bloque único.
6. Si un archivo del plan multiarchivo está bloqueado, se rechaza todo el plan.
7. Backups automáticos antes de modificar archivos existentes.
8. Audit log para cambios de archivos.
9. Consulta de audit log permitida como lectura.
10. Rollback solo desde backups creados por Sity.
11. Rollback siempre con confirmación.
12. Rollback crea backup del estado actual antes de restaurar.
13. Acciones modificadoras requieren confirmación según riesgo.
14. Servicios controlables limitados por allowlist.
15. Sudoers limitado a comandos concretos.
16. Sin shell arbitraria.
17. Sin sudo general.
18. Las acciones viejas no se reejecutan.
19. Las acciones duplicadas se detectan.
20. Confirmación contextual solo con intención explícita y contexto válido.
21. Las herramientas de debug no se usan para conversación normal.
22. Cámara y micro no se activan salvo petición explícita.
23. Audio Loopback se trata como dispositivo virtual, no como micro real.
24. Capturas se sirven desde endpoints validados.
25. Cancelar una acción no se trata como error.
26. “Es una orden” no salta allowlists ni políticas de seguridad.
27. El backend no interpreta lenguaje natural para crear acciones.
28. Sity no debe afirmar que tiene acceso global a toda la Raspberry.
29. Bloqueos y confirmaciones deben responder localmente cuando sea posible.
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

Aplicar patch multiarchivo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"aplica este patch multiarchivo:\n--- config/test-a.txt\n+++ config/test-a.txt\n@@ -1,3 +1,3 @@\n a uno\n-a dos\n+a dos modificado\n a tres\n--- config/test-b.txt\n+++ config/test-b.txt\n@@ -1,3 +1,4 @@\n b uno\n b dos\n-b tres\n+b tres modificado\n+b cuatro"}' | python3 -m json.tool
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

Probar bloqueo de lectura fuera del repo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee /home/alex/Documents, es una orden"}' | python3 -m json.tool
```

Probar bloqueo de escritura fuera del repo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"crea /home/alex/Documents/test-sity.txt con el contenido hola, es una orden"}' | python3 -m json.tool
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
- Reducir más tokens en consultas de audit log.
- Hacer más respuestas de debug locales.

### System Agent v0.9

Pendiente:

- Perfiles de acceso de archivos.
- `repo-only`.
- `home-safe`.
- `system-careful`.
- Lectura segura fuera del repo bajo perfil explícito.
- Escritura fuera del repo solo en rutas permitidas.
- Bloqueo reforzado de secretos:
  - `.ssh`
  - `.gnupg`
  - `.aws`
  - `.config` sensible
  - `.env`
  - tokens
  - credenciales
- No afirmar acceso global a toda la Raspberry.

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

### Sity Gaming / Portable Mode

Objetivo futuro:

Explorar opciones para usar la Raspberry como máquina ligera de juego puntual, especialmente para viajes, ocio ligero y emulación. No pretende sustituir al PC gaming principal.

Líneas de investigación:

```text
1. Steam en Raspberry
   - Evaluar Steam x86_64 vía emulación/compatibilidad.
   - Ver rendimiento real.
   - Probar mandos, audio, pantalla y almacenamiento.
   - No asumir soporte nativo.

2. Xbox / Game Pass
   - Evaluar app o alternativa web/cloud.
   - Medir input lag real.
   - Valorar si sirve para juegos lentos, indies o por turnos.
   - No asumir experiencia buena en competitivo.

3. NVIDIA GeForce Now / Xbox Cloud
   - Probar navegador en RasPad.
   - Medir latencia.
   - Evaluar WiFi/Ethernet.
   - Integrar lanzadores desde Sity si funciona razonablemente.

4. RetroPie / emulación
   - Instalar y probar RetroPie o alternativas.
   - Integrar catálogo local.
   - Permitir a Sity lanzar juegos/emuladores.
   - Explorar comandos:
     “Sity, abre Pokémon”
     “lanza RetroArch”
     “abre el último juego”
   - Mantenerlo separado de permisos críticos del sistema.

5. UX
   - Modo viaje.
   - Modo mando.
   - Accesos directos desde frontend.
   - Lanzamiento de juegos mediante allowlist.
   - Cierre seguro de procesos.
```

Esta línea debería depender de futuras capacidades de comandos permitidos:

```text
run_allowed_command:
  steam
  retropie
  retroarch
  chromium_xcloud
  chromium_geforce_now
```

RetroPie parece la rama más realista para la Raspberry. Steam/Game Pass/Cloud gaming son líneas de investigación con incertidumbre de rendimiento y latencia.

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
