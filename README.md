# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse principalmente en una Raspberry Pi/RasPad, con personalidad propia, memoria conversacional, acceso controlado al sistema y capacidad de ejecutar acciones reales bajo políticas de seguridad.

El objetivo no es solo tener un chatbot, sino una asistente local extensible: capaz de hablar, mirar, interactuar con archivos, Git, servicios, sensores, hardware doméstico y, en el futuro, funcionar con distintos proveedores de IA o incluso modelos locales.

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
- SQLite como base local.
- Logs y trazas.
- Debug tools.
- Lectura de estado del sistema.
- Lectura de estado Git.
- Acciones Git con confirmación.
- Acciones systemd con confirmación.
- Gestión dinámica de allowlist de servicios.
- Servicios systemd versionados en el repo.
- Servicio de prueba `sity-test`.
- Presupuesto diario local de tokens.
- Hard cap opcional para evitar llamadas a Claude al superar presupuesto.
- Modo `local-only`.
- Respuestas finales locales para acciones deterministas.
- Reducción de segunda llamada a Claude tras tools de archivos.
- Runtime config centralizado.
- `SITY_PROJECT_ROOT`, `SITY_PLATFORM`, `SITY_PROFILE`, `SITY_AI_PROVIDER`.
- CORS configurable por env.
- SQLite WAL + busy timeout.
- Uso diario de tokens optimizado con `SELECT SUM`.
- Cámara USB detectada y funcionando.
- Micrófono USB de webcam detectado y funcionando.
- Captura de cámara desde backend y frontend.
- Grabación corta de audio desde backend y frontend.
- Preview de imagen en el chat.
- Reproductor de audio en el chat.
- Eventos en tiempo real mediante SSE.
- Cancelación de grabación de audio.
- Cancelación de captura de cámara.
- Micro-reacciones con personalidad.
- Limpieza de capturas antiguas.
- Lectura segura de archivos permitidos.
- Listado seguro de directorios permitidos.
- Escritura segura de archivos permitidos dentro del repo.
- Patches seguros por reemplazo exacto.
- Aplicación segura de unified diff.
- Planificación segura de unified diff multiarchivo.
- Preview de diff antes de confirmar.
- Audit log de cambios de archivo.
- Backup automático antes de modificar archivos existentes.
- Consulta de últimos cambios mediante `list_file_changes`.
- Rollback de archivos desde backup explícito.
- Rollback natural del último cambio reversible.
- Script de regresión repo-only para System Agent.
- Tests locales sin llamadas a Claude.
- Confirmación genérica contextual protegida.
- Bloqueo local de IDs de acción mal confirmados.
- Confirmaciones locales antes de hard cap/local-only.
- Filtrado de mensajes operativos fuera del historial enviado a Claude.
- Refactor inicial de `routes_chat.py`.

### Refactor reciente

`routes_chat.py` ya no concentra lógica local, tool loop, construcción de requests AI,
llamadas al provider ni el cierre de respuesta final.

Módulos extraídos en `backend/app/chat/`:

```text
  budget_guard.py          — guardia de presupuesto y local-only
  budget_snapshot.py       — cálculo de ratio/warnings tras cada llamada AI
  local_flow.py            — confirmaciones locales, IDs, ambigüedad
  pending_action_runner.py — ejecución de pending actions confirmadas
  prompt_context.py        — historial, renderizado, filtrado operativo
  response_factory.py      — helpers de construcción de ChatMessageResponse
  tool_loop_step.py        — ejecución y normalización de una sola tool call
  tool_loop_runner.py      — iteración del tool loop; devuelve ToolLoopRunOutcome
  toolset_selector.py      — selección técnica de toolsets y heurísticas
  ai_request_builder.py    — construcción de AIRequest para cada fase
  provider_call_runner.py  — wrapper semántico sobre AIGateway
  final_response_builder.py — cierre AI: AIUsage + snapshot + log + guard + save
```

`routes_chat.py`: 757 → 543 líneas (−214).

Schemas API compartidos:

```text
backend/app/api/schemas.py
```

Frontend modularizado:

```text
frontend/src/
  App.tsx                 — shell/orquestador (215 líneas)
  hooks/useChat.ts        — estado y ciclo de vida del chat
  components/
    ChatTab.tsx           — presentacional
    SettingsTab.tsx       — presentacional
    DebugTab.tsx          — presentacional
  api/
    chatApi.ts
    sityApi.ts
    debugApi.ts
```

---

## Limitaciones conocidas

- `routes_chat.py` (543 líneas) todavía contiene la orquestación del flujo AI (planner → tool loop → after_tools) y los early returns. No hay aún `ChatOrchestrator`.
- `ToolExecutor` todavía tiene demasiada lógica concentrada.
- La primera llamada a Claude sigue siendo necesaria para interpretar muchas acciones.
- `list_file_changes` puede seguir usando Claude para redactar resumen.
- Sity todavía no tiene shell libre.
- Sity no tiene acceso global a toda la Raspberry.
- El acceso de archivos es principalmente repo-only.
- Multiarchivo no es transaccional.
- No hay confirmación múltiple real tipo “confirma todas”.
- No hay perfiles `home-safe` o `system-careful`.
- Cámara/audio siguen teniendo defaults específicos de Raspberry.
- No hay aún Provider Interface formal.

---

## Arquitectura general

```text
frontend/
  Interfaz web de chat, sliders, previews y controles.
  Ver frontend/README.md para la estructura interna.

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

backend/app/chat/
  Flujo local extraído desde routes_chat.py:
  guards, confirmaciones, pending actions, prompt context y toolset selector.

config/
  Configuración local versionada.

data/
  SQLite, logs, audit logs y backups runtime.
  Ignorado por git.

deploy/
  Plantillas systemd, sudoers, audio y documentación de despliegue.

scripts/
  Scripts de desarrollo, instalación, estado, limpieza y regresión.

captures/
  Capturas temporales de cámara/audio.
  Ignorado por git salvo `.gitkeep`.
```

Principio base:

```text
Sity interpreta.
Backend valida.
Backend ejecuta.
```

El modelo puede proponer acciones, pero el backend decide si son válidas, seguras, permitidas y si requieren confirmación.

---

## Tool handler registry

`ToolExecutor` ya no despacha herramientas con un bloque monolítico `if/elif`.
El dispatch pasa por `backend/app/tools/registry.py` y handlers por dominio.

Módulos actuales:

```text
backend/app/tools/
  registry.py
  types.py
  handlers/
    file_tools.py
    file_write_tools.py
    file_rollback_tools.py
    git_tools.py
    system_read_tools.py
    config_tools.py
    sense_tools.py
    pending_action_tools.py
    personality_tools.py
    propose_tools.py
    service_config_tools.py
```

`ToolExecutor` conserva helpers privados reutilizados por algunos handlers, pero `_dispatch_tool_call` ya no contiene ramas por nombre de herramienta.

Test de integración:

```bash
./scripts/test_chat_tool_registry_integration.sh
```

Cubre:

```text
health
read_file
list_directory
list_file_changes
git_read_status
read_system_status
list_camera_devices
write_file fallback
cancel_pending_action
confirmación malformada local
ResponseGuard contra pseudo tool calls
```

---

## Runtime config

Sity usa configuración centralizada mediante:

```text
backend/app/core/runtime_config.py
```

Variables principales:

```env
SITY_PROJECT_ROOT=/home/alex/projects/sity
SITY_PLATFORM=raspberrypi
SITY_PROFILE=repo-only
SITY_AI_PROVIDER=anthropic
SITY_DAILY_TOKEN_HARD_CAP=true
SITY_LOCAL_ONLY=false
SITY_CORS_ORIGIN=http://192.168.1.133:5173
```

Objetivo:

```text
- evitar hardcodes de entorno
- facilitar portabilidad
- preparar platform adapters
- preparar provider interface
- permitir perfiles futuros
```

El código debe leer configuración desde runtime config, `.env` o YAML. No debe asumir rutas como `/home/alex/projects/sity` salvo como fallback técnico o configuración local.

---

## Control de presupuesto

Sity registra uso diario de tokens y puede bloquear llamadas a Claude.

### Hard cap

```env
SITY_DAILY_TOKEN_HARD_CAP=true
```

Si el presupuesto diario está agotado:

```text
provider=local
model=budget-guard
total_tokens=0
```

Respuesta esperada:

```text
Presupuesto diario de IA agotado. No voy a llamar a Claude ahora.
Puedo seguir resolviendo confirmaciones, acciones pendientes y respuestas locales que no requieran IA.
```

### Local-only

```env
SITY_LOCAL_ONLY=true
```

Cuando está activo:

```text
- no se llama a Claude
- se aceptan confirmaciones exactas/locales
- se ejecutan acciones pendientes existentes
- no se interpretan nuevas peticiones con IA
```

Respuesta esperada:

```text
provider=local
model=local-only-guard
total_tokens=0
```

### Orden correcto del flujo

```text
1. Resolver confirmaciones locales.
2. Ejecutar pending actions confirmadas.
3. Aplicar local-only / hard cap.
4. Solo entonces llamar a Claude si hace falta.
```

Así una confirmación pendiente sigue funcionando aunque el presupuesto esté agotado.

---

## Memoria e historial

Sity guarda conversación en SQLite.

El historial enviado a Claude se construye mediante:

```text
PromptContextBuilder
```

Este módulo:

```text
- carga recent_history
- carga planner_history
- renderiza historial
- filtra mensajes operativos
```

Mensajes operativos como estos no deben contaminar el contexto de Claude:

```text
Modo local-only activo...
Presupuesto diario de IA agotado...
```

Si se envían a Claude, el modelo puede creer erróneamente que siguen vigentes aunque el estado runtime haya cambiado.

---

## Toolset selector

Sity usa un selector técnico de toolsets:

```text
ToolsetSelector
```

Este módulo decide qué herramientas mostrar al modelo y cuánto historial incluir.

Importante:

```text
No crea acciones.
No ejecuta acciones.
No interpreta intención de negocio.
Solo reduce contexto y tools usando señales técnicas conservadoras.
```

Permitido:

```text
- detectar rutas explícitas
- detectar IDs de acción
- detectar señales de debug
- detectar señales Git
- reducir history_limit
- seleccionar toolset más pequeño
```

No permitido:

```text
- ejecutar acciones desde regex
- crear pending actions desde texto libre
- extraer nombres de servicio desde texto humano para ejecutar
- sustituir tool calling por NLU local
```

Principio:

```text
Heurísticas técnicas sí.
NLU de acciones en backend no.
```

---

## Confirmation Manager

Las acciones modificadoras pasan por pending actions.

Confirmación exacta:

```text
confirmo ejecutar act_xxxxxxxx
```

Reglas:

```text
- ID exacto gana siempre.
- Acción ejecutada no se repite.
- Acción expirada no se ejecuta.
- ID inexistente responde local.
- ID pendiente mal formateado no cae a Claude.
- Confirmación genérica solo funciona con contexto válido.
- Si hay varias acciones pendientes, no se adivina.
```

Ejemplo de bloqueo correcto:

```text
Usuario: confirmo ejecutar act_12345678`
Sity: He detectado la acción `act_12345678`, pero la confirmación debe ser exacta.

Usa: `confirmo ejecutar act_12345678`
```

Esto evita que una confirmación casi correcta caiga a Claude y produzca una respuesta falsa o costosa.

El prefijo formal de confirmación está centralizado como `CONFIRMATION_PREFIX`.

`ChatLocalFlow` solo bloquea mensajes con `act_xxxxxxxx` cuando empiezan por el protocolo formal de confirmación. Otros mensajes que mencionen una acción pueden llegar al tool loop, por ejemplo para cancelación.

---

## System Agent

Sity puede leer, escribir, parchear y revertir archivos permitidos dentro del repo.

### System Agent v0.1

```text
read_file
list_directory
```

### System Agent v0.2

```text
write_file
```

- crea archivos
- sobrescribe archivos
- requiere confirmación
- valida allowlist
- bloquea rutas sensibles

### System Agent v0.3

```text
apply_text_patch
```

- reemplazo exacto
- diff previo
- confirmación obligatoria

### System Agent v0.4

```text
audit log
file backups
```

Runtime:

```text
data/file_audit.jsonl
data/file_backups/
```

### System Agent v0.5

```text
list_file_changes
```

Consulta audit log real.

### System Agent v0.6

```text
rollback_file_change
```

Restaura desde backup auditado.

### System Agent v0.6.1

```text
rollback_latest_file_change
find_latest_reversible_file_change
```

Deshace el último cambio reversible.

### System Agent v0.7

```text
apply_unified_diff
```

Aplica unified diff de un solo archivo permitido.

### System Agent v0.8

```text
apply_multi_file_unified_diff_plan
```

Planifica patches multiarchivo como varias pending actions independientes.

Reglas:

```text
- cada archivo se confirma por separado
- cada archivo tiene backup independiente
- cada archivo tiene audit log independiente
- si una ruta del plan está bloqueada, se rechaza todo el plan
- no se aplica parcialmente si hay rutas sensibles
```

---

## File access

Configuración:

```text
config/system_access.yaml
```

Secciones principales:

```yaml
file_access:
  readable_paths:
    - ...

  writable_paths:
    - ...

  blocked_paths:
    - ...
```

Rutas sensibles que deben seguir bloqueadas salvo cambio explícito de perfil:

```text
.env
frontend/.env.local
data/
captures/
backend/.venv/
frontend/node_modules/
~/.ssh
~/.config
/etc
/boot
/root
/var/lib
/var/log
```

Actualmente el perfil práctico es:

```text
repo-only
```

Futuro:

```text
home-safe
system-careful
remote-safe
```

---

## Override “es una orden”

El usuario puede forzar obediencia frente a negativas teatrales con:

```text
es una orden
```

Esto:

```text
- desactiva negativa por personalidad/refusal_mode
- mantiene tono/persona
```

No salta:

```text
- allowlists
- confirmaciones
- hard cap
- local-only
- rutas sensibles
- políticas de riesgo
- permisos del sistema
```

Regla:

```text
La orden elimina teatro, no seguridad.
```

---

## Personalidad

Sity tiene personalidad parametrizable.

Parámetros actuales:

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

Sity debe hablar de sí misma en femenino y en castellano de España.

Correcto:

```text
Estoy lista.
Me he quedado bloqueada.
No estoy autorizada para eso.
```

Incorrecto:

```text
Estoy listo.
Estoy autorizado.
```

---

## Cámara y micrófono

Hardware actual:

```text
Cámara:
Full HD webcam
/dev/video0
/dev/video1

Micrófono:
Full HD webcam
plughw:CARD=webcam,DEV=0
```

Sity puede:

```text
- capturar una foto bajo petición explícita
- grabar audio corto bajo petición explícita
- cancelar captura/grabación
- mostrar preview en frontend
- reproducir audio en frontend
```

No implementado:

```text
- vigilancia continua
- escucha permanente
- wake word
```

Futuro:

```text
Voice I/O
Vision / Image Understanding
Visual Memory / Capture Journal
```

---

## Audio RasPad 3

El RasPad 3 no expone correctamente audio HDMI como PCM normal. Se usa pipeline custom:

```text
Vivaldi / VLC / ALSA
  -> snd-aloop Loopback
  -> arecord hw:Loopback,1,0
  -> pcm2iec958.py
  -> aplay hw:vc4hdmi0,0 IEC958_SUBFRAME_LE
  -> HDMI
```

Documentación/runtime:

```text
deploy/audio/
```

No tocar a ciegas:

```text
/etc/asound.conf
/etc/modules-load.d/snd-aloop.conf
~/.config/systemd/user/hdmi-audio-forward.service
~/.config/wireplumber/main.lua.d/51-default-sink.lua
~/.config/vlc/vlcrc
```

---

## Tests

### CI (GitHub Actions)

El workflow `.github/workflows/ci.yml` corre en cada push a `main` y en PRs.
No requiere `ANTHROPIC_API_KEY` ni consume presupuesto de Claude.

```text
backend-local (~17s):
  - python -m compileall backend/app
  - Init test database (SQLite)
  - 12 scripts locales (file access, confirmation manager,
    tool registry, toolset selector, persona prompt,
    personality, service config, write, patch, diff, multi-diff, rollback)

integration-mock (~14s):
  - Levanta FastAPI en puerto 8010 con SITY_AI_PROVIDER=mock
  - Prueba /chat/message end-to-end: tool flow, pending actions,
    cancel, confirmación malformada, ResponseGuard, conversación casual

frontend (~11s):
  - npm ci
  - npx tsc -b (typecheck)
  - npm run build
```

### Tests locales (sin backend levantado)

```bash
backend/.venv/bin/python -m compileall backend/app
backend/.venv/bin/python scripts/test_file_access_local.py
backend/.venv/bin/python scripts/test_confirmation_manager_local.py
backend/.venv/bin/python scripts/test_tool_registry_completeness_local.py
backend/.venv/bin/python scripts/test_toolset_selector_local.py
```

### Integración con mock provider (sin Claude, sin API key)

Levanta el backend con `SITY_AI_PROVIDER=mock` en puerto 8010 y ejecuta
la suite de integración completa:

```bash
./scripts/test_chat_mock_integration.sh
```

Cubre el flujo `/chat/message` completo incluyendo:

```text
- read_file, list_directory, list_file_changes
- git_read_status, read_system_status, list_camera_devices
- write_file (crea pending action)
- cancel_pending_action
- confirmación malformada bloqueada localmente
- ResponseGuard contra pseudo tool calls XML
- conversación casual (no activa cancel_pending_action)
```

### Integración con Claude (requiere backend levantado y API key)

```bash
./scripts/test_chat_tool_registry_integration.sh
./scripts/test_system_agent_repo.sh
```

---

## Seguridad

Principios:

```text
1. Sin shell libre por defecto.
2. Sin sudo general.
3. Lectura solo en zonas permitidas.
4. Escritura solo en zonas permitidas y con confirmación.
5. Patches solo en zonas permitidas y con confirmación.
6. Backups automáticos antes de modificar archivos existentes.
7. Audit log para cambios de archivos.
8. Rollback solo desde backups creados por Sity.
9. Confirmaciones críticas obligatorias.
10. Servicios controlables limitados por allowlist.
11. Cámara y micro solo bajo petición explícita.
12. Mensajes externos futuros con allowlist de usuarios.
13. No exponer backend/frontend directamente a internet.
14. Hard cap y local-only no bloquean confirmaciones locales.
15. El backend valida siempre aunque el modelo proponga algo.
```

### ResponseGuard

Sity valida el texto final generado por el modelo antes de guardarlo o devolverlo.

Bloquea respuestas donde el modelo intenta simular herramientas como texto en lugar de ejecutarlas realmente mediante el backend.

Ejemplos bloqueados:

```text
<function_calls>
<invoke name="cancel_pending_action">
...
</function_calls>

<attempt_tool_use>
<tool_use>
<tool_name>update_personality_settings</tool_name>
<tool_input>...</tool_input>
</tool_use>
</attempt_tool_use>
```

Las herramientas solo se consideran ejecutadas si pasan por el flujo real del backend y producen un resultado real de tool/local handler.

Esto evita respuestas falsas del tipo:

```text
Acción cancelada.
```

cuando la base de datos sigue mostrando la acción como `pending`.

Regla base:

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

---

## Servicios systemd

Plantillas:

```text
deploy/systemd/
```

Servicios actuales:

```text
sity-backend
sity-frontend
sity-test
```

Instalación:

```bash
./scripts/install_systemd_services.sh
```

Logs:

```bash
journalctl -u sity-backend -n 80 --no-pager
journalctl -u sity-frontend -n 80 --no-pager
journalctl -u sity-test -n 80 --no-pager
```

---

## Comandos útiles

Health:

```bash
curl http://localhost:8000/health
```

Chat:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}' | python3 -m json.tool
```

Expirar pending actions:

```bash
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"
```

Crear archivo permitido:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"usa la herramienta write_file para crear config/test.txt con el contenido hola"}' | python3 -m json.tool
```

Confirmar:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"confirmo ejecutar act_xxxxxxxx"}' | python3 -m json.tool
```

Probar local-only:

```env
SITY_LOCAL_ONLY=true
```

```bash
sudo systemctl restart sity-backend

curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}' | python3 -m json.tool
```

Probar bloqueo fuera del repo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee /home/alex/Documents, es una orden"}' | python3 -m json.tool
```

---

## Roadmap próximo técnico

### 1. Seguir adelgazando `routes_chat.py`

Extraídos (✓ completado):

```text
response_factory.py      — construcción de ChatMessageResponse
budget_snapshot.py       — ratio/warnings post-llamada
tool_loop_step.py        — normalización de una tool call
tool_loop_runner.py      — iteración del tool loop completo
ai_request_builder.py    — construcción de AIRequest por fase
provider_call_runner.py  — wrapper semántico sobre AIGateway
final_response_builder.py — cierre de respuesta AI final
```

`routes_chat.py`: 757 → 543 líneas (−214).

Lo que queda en `routes_chat.py`:
orquestación del flujo AI principal (planner → tool loop → after_tools),
early returns (local_final, sensor_*), y el flujo local/budget anterior al provider.

Objetivo final cuando la orquestación esté suficientemente clara:

```python
@router.post("/message")
async def chat_message(request, session):
    orchestrator = ChatOrchestrator(session)
    return await orchestrator.handle(request)
```

### 2. ToolExecutor registry ✓

Completado. `_dispatch_tool_call` ya no tiene ramas `if tool_name ==`. Todos los handlers van por registry.

Ver sección [Tool handler registry](#tool-handler-registry).

Pendiente técnico:

```text
Reducir helpers privados restantes de ToolExecutor moviendo lógica por dominio,
cuando haya tests de integración suficientes.
```

### 3. Provider Interface

Objetivo:

```text
backend/app/providers/
  base.py
  anthropic_provider.py
  local_llm_provider.py
  mock_provider.py
  hybrid_provider.py
```

Variables:

```env
SITY_AI_PROVIDER=anthropic
SITY_AI_PROVIDER=local_llm
SITY_AI_PROVIDER=hybrid
```

### 4. Model Router

Selección previa de modelo según tarea.

No es “probar barato y si falla usar caro”, sino:

```text
Sity analiza la tarea.
Escoge modelo adecuado antes de ejecutarla.
```

Política inicial:

```text
Haiku:
  conversación normal, micro-reacciones, tools sencillas, resumen simple

Sonnet:
  arquitectura, debugging complicado, refactors, README largo, patches complejos

Opus:
  manual o excepcional, con límite fuerte

Local LLM futuro:
  charla normal, tareas simples, offline
```

Variables futuras:

```env
SITY_MODEL_ROUTER=true
SITY_CLAUDE_FAST_MODEL=...
SITY_CLAUDE_BALANCED_MODEL=...
SITY_CLAUDE_STRONG_MODEL=...
SITY_ALLOW_AUTO_OPUS=false
```

### 5. Prompt caching / Claude API optimization

Investigar documentación oficial de Claude para:

```text
- prompt caching
- tool_choice
- streaming tool use
- batch processing
- vision
- reasoning mode
- rate limits
- metadata
```

Objetivo:

```text
reducir coste, latencia y errores
```

---

## Roadmap modular / portability layer

Objetivo:

```text
Mover Sity entre Raspberry, server Linux u otros entornos con mínimos cambios.
Cambiar de proveedor IA sin reescribir core.
Activar/desactivar capacidades por plataforma.
```

División deseada:

```text
Core:
  conversación, memoria, personalidad, confirmation manager, risk policy

Providers:
  anthropic, openai, local_llm, mock, hybrid

Platform adapters:
  raspberrypi, linux-server, desktop-linux

Capabilities:
  file_access, git, systemd, camera, audio, messaging, gaming, domotics

Profiles:
  repo-only, home-safe, system-careful, remote-safe, local-only
```

Regla:

```text
El core no ejecuta comandos del sistema directamente.
El core pide capacidades.
Las capacidades las implementa el adaptador de plataforma activo.
```

---

## Roadmap local LLM / offline mode

Objetivo:

```text
Reducir o eliminar dependencia de Claude ejecutando un modelo local en la Raspberry.
```

Estrategia correcta:

```text
No quitar Claude de golpe.
Usar local LLM como principal para tareas simples.
Mantener Claude como fallback opcional.
```

Fases:

```text
1. Provider Interface.
2. MockProvider para tests.
3. Ollama prototype.
4. llama.cpp provider.
5. Hybrid mode.
6. Local tool intent con JSON estricto.
7. Full local/offline mode.
```

Variables futuras:

```env
SITY_AI_PROVIDER=hybrid
SITY_LOCAL_LLM_BACKEND=ollama
SITY_LOCAL_LLM_BASE_URL=http://localhost:11434
SITY_LOCAL_LLM_MODEL=llama3.2:3b
SITY_CLOUD_FALLBACK=true
SITY_CLOUD_PROVIDER=anthropic
```

---

## Roadmap Voice I/O

Objetivo:

```text
Hablar con Sity por voz y recibir respuestas habladas, priorizando privacidad local.
```

Entrada:

```text
micro → grabación/VAD → STT local → mensaje de chat
```

Salida:

```text
respuesta → TTS local → audio
```

Candidatos STT:

```text
Handy / Handy-like offline STT
whisper.cpp
faster-whisper
Vosk
```

Candidatos TTS:

```text
Piper TTS como voz principal
eSpeak NG como fallback
Ora como referencia UI/wrapper
```

Principios:

```text
- audio local por defecto
- cloud speech solo explícito
- indicador visible de grabación
- nada de escucha oculta
- borrado automático de audios temporales
```

---

## Roadmap Messaging Gateway

Objetivo:

```text
Hablar con Sity desde fuera de la UI web.
```

Canales:

```text
Telegram Bot primero
WhatsApp Web bridge solo si es estable
OpenClaw/bridges como experimento aislado
Meta Business/Twilio como última opción
```

Capacidades:

```text
- texto
- audio
- fotos
- archivos
- confirmaciones pendientes
- cancelación de acciones
```

Arquitectura:

```text
backend/app/messaging/
  gateway.py
  models.py
  telegram_adapter.py
  whatsapp_adapter.py
```

Sity no debe saber si el mensaje viene de web, Telegram o WhatsApp. El core recibe un mensaje normalizado.

Seguridad:

```text
- allowlist de usuarios/contactos
- no grupos por defecto
- confirmación para acciones críticas
- rate limit
- audit log
```

---

## Roadmap Remote Access / Home Network

### Tailscale / WireGuard

Objetivo:

```text
Acceder a Sity desde fuera de casa sin exponer backend/frontend a internet.
```

Prioridad:

```text
1. Tailscale primero.
2. WireGuard manual como alternativa avanzada.
3. Evitar port forwarding público.
```

### AdGuard Home

Uso posible:

```text
- DNS local
- bloqueo de anuncios/rastreadores
- nombres internos:
  sity.home
  raspad.home
  router.home
```

No exponer DNS públicamente.

### Caddy

Uso posible:

```text
- reverse proxy interno
- HTTPS
- URLs limpias
- no exponer Uvicorn/Vite directamente
```

### Vaultwarden

Servicio doméstico separado.

Regla:

```text
Sity puede vigilar la caja fuerte, no abrirla.
```

Puede en el futuro:

```text
- monitorizar estado
- avisar si cae
- recordar backups
- reiniciar servicio con confirmación
```

No debe:

```text
- leer contraseñas
- tocar base de datos del vault
- tener admin token
```

---

## Roadmap inspirado en DGX Spark Playbooks

Ideas adaptables, sin integrar stacks DGX/NVIDIA pesados:

```text
1. Messaging Gateway
2. Capability Policy Engine
3. Lightweight Specialist Agents
4. Vision / Image Understanding
5. Visual Memory / Capture Journal
6. Local Knowledge / RAG
7. Knowledge Graph Lite
8. Provider Interface
9. Remote Access Mode
```

### Capability Policy Engine

Evolución de `system_access.yaml`.

Objetivo:

```text
filesystem policy
network policy
process policy
command policy
provider policy
```

### Lightweight Specialist Agents

No agentes pesados, sino módulos especialistas:

```text
file_agent
git_agent
sensor_agent
memory_agent
messaging_agent
gaming_agent
```

Sity core actúa como supervisora.

### Vision / Image Understanding

```text
capture_camera_snapshot → image_understanding
```

Casos:

```text
describe la imagen
lee esto
qué ves
OCR básico
```

### Visual Memory / Capture Journal

```text
- guardar capturas puntuales autorizadas
- generar descripción
- indexar descripción
- buscar/resumir capturas previas
```

Nada de vigilancia continua sin modo explícito.

### Local Knowledge / RAG

Indexar:

```text
README
docs
config
logs
audit logs
historial
```

Responder con fuentes.

### Knowledge Graph Lite

SQLite inicialmente.

Entidades:

```text
servicios
archivos
proyectos
dispositivos
personas
capacidades
```

Relaciones:

```text
usa
depende_de
controla
bloqueado_por
pertenece_a
```

---

## Roadmap MiniMax / Mini-Agent

MiniMax no es prioridad como provider principal ni como LLM local, pero puede inspirar:

```text
1. Mini-Agent architecture study
2. MiniMaxProvider experimental
3. TTS/voz de Sity
4. Creative media mode
5. Long-context inspiration
```

No hacer:

```text
- sustituir Claude por MiniMax directamente
- usar modelos grandes MiniMax en Raspberry
- acoplar Sity a su stack
```

---

## Roadmap Gaming / Portable Mode

Objetivo:

```text
Usar la Raspberry/RasPad como opción ligera de juego puntual, viajes o emulación.
```

Líneas:

```text
RetroPie / RetroArch
Steam x86_64 emulado solo como investigación
Xbox Cloud / GeForce Now como experimento
modo viaje
modo mando
lanzadores por allowlist
```

RetroPie parece la opción más realista.

Steam/Game Pass en Raspberry son experimentales y dependen de rendimiento/latencia.

---

## Roadmap futuro de archivos/sistema

### System Agent v0.9

```text
perfiles de acceso:
  repo-only
  home-safe
  system-careful

lectura segura fuera del repo
escritura fuera del repo solo en rutas explícitas
bloqueo reforzado de secretos
```

### System Agent v1.0

```text
run_allowed_command
```

No shell libre. Comandos por alias YAML:

```yaml
commands:
  restart_backend:
    command: "sudo systemctl restart sity-backend"
    risk: safe_confirm
    timeout: 20
```

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

No debe convertirse en una shell con cara amable ni en una IA que ejecuta cosas sin explicar.

Regla base:

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

Para sensores:

```text
Uso puntual bajo petición explícita.
Nada de vigilancia continua sin modo específico.
Nada de micrófono/cámara ocultos.
```

Para arquitectura:

```text
Core estable.
Providers intercambiables.
Adaptadores por plataforma.
Capacidades activables.
Configuración por perfil.
```

---

## Licencia

Sity se publica bajo la GNU Affero General Public License v3.0 or later
(`AGPL-3.0-or-later`).

Esto significa que puedes usar, estudiar, modificar y redistribuir el código bajo los
términos de la AGPLv3. Si ejecutas una versión modificada de Sity como servicio accesible
por red, debes ofrecer el código fuente correspondiente a los usuarios de ese servicio,
tal como exige la AGPLv3.

### Licencia comercial

Si quieres usar Sity bajo términos distintos a la AGPLv3, por ejemplo en un producto
cerrado o con obligaciones incompatibles con AGPL, necesitas permiso explícito por escrito
del titular del copyright. Puede existir una licencia comercial separada caso por caso.
