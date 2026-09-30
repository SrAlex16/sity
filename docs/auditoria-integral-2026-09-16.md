## Auditoría integral post-Remake (2026-09-16) — revisión pasiva completa

**Contexto:** revisión de código, documentación, tests y CI realizada tras cerrar la
Operación Remake (9 fases) y la campaña de auditoría con agentes de IA (36 hallazgos).
Revisión **pasiva**: lectura de código, ejecución de suites existentes y análisis
estático. Sin interacción con Sity en producción, sin modificar DB ni código.

### Qué se revisó y cómo

- `pyflakes` sobre `backend/app/` (208 archivos): 0 avisos nuevos; los 27 existentes son
  side-effect imports de registro ya catalogados (Grupo B).
- Aislamiento por usuario: todas las `select()` sobre las 30 tablas con `user_id`/`session_id`
  (Goal, Episode, SemanticFact, FileArtifact, ProceduralPattern, etc.) — filtro correcto en
  todos los puntos revisados, incluidos `routes_files.py` (3 endpoints) e `initiative/`.
- Capas: ningún módulo de `cognition/`, `social/`, `core/`, `memory/` importa de `api/`
  (sin dependencias invertidas).
- Suite backend ejecutada de forma independiente con la misma configuración que el CI
  (`SITY_AI_PROVIDER=mock`, `-m "not behavior_regression"`): **3104 passed, 0 failed**.
- Suite frontend (vitest) ejecutada con config temporal sin `mkcert`: **12/12 passed**.
- Auth, secretos, cabeceras HTTP, workflow de CI, coherencia de `docs/`.

### Fortalezas confirmadas

- **Defensa en profundidad real** en control de acceso: `_ADMIN_ONLY_TOOL_NAMES` en
  construcción del toolset + gate en `ToolExecutor._dispatch_tool_call` + verificación
  post-generación (`response_integrity.py`). Tres capas independientes.
- `routes_uploads.py`: validación sólida contra path traversal (extensión, `..`, resolución
  de ruta contra raíz).
- CI del backend correctamente aislado: `SITY_AI_PROVIDER=mock`, sin API key real — los 14
  tests de modelo real se saltan sin coste ni flakiness estocástica.
- `DELETE /files/{id}` devuelve 404 sin revelar si el ID pertenece a otro usuario.
- Sin secretos en el historial de git ni credenciales hardcodeadas.
- Helper `utc_now()` centralizado (65 usos) — buena práctica ya establecida.
- Documentación de fases (`docs/remake/*`) y mapa maestro del pipeline cognitivo al día y
  coherentes con el código (verificado: `prediction_error` correctamente documentado como
  "reservado para fase futura", no como implementado).

### Debilidades encontradas

| # | Hallazgo | Severidad | Evidencia |
|---|----------|-----------|-----------|
| A1 | `GET /uploads/images/{filename}` **sin autenticación ni comprobación de propietario**. Cualquier petición que conozca el nombre (UUID4) descarga la imagen de cualquier usuario. Las URLs se exponen en `/chat/current` (`image_urls`) y en logs (`rel_path`). Seguridad por oscuridad. | **Media** | `routes_uploads.py` — el handler no tiene `Depends(get_current_user)` |
| A2 | `/auth/login` y reset de contraseña **sin rate-limit** (`GuestIPRateLimiter` solo cubre mensajes de invitados). Mitigado parcialmente por reCAPTCHA v3 (umbral 0.5), pero reCAPTCHA **falla abierto** si `RECAPTCHA_SECRET_KEY` no está configurada, y la clave se lee una sola vez al importar el módulo (mismo patrón que `jwt_secret_missing`). Un despiste de configuración deja el login sin protección con solo un WARN. | **Media-alta** | `routes_auth.py:177-182`, `recaptcha.py:16-34` |
| A3 | **Tests de frontend nunca se ejecutan en CI**. 4 archivos / 12 tests (incluidos los de regresión de acceso Guest y cuota agotada) solo protegen si alguien los corre a mano. | **Media** | `.github/workflows/ci.yml` — job mobile solo hace `tsc -b` + `build` |
| A4 | `vite-plugin-mkcert` cargado **incondicionalmente** en `vite.config.ts`: descarga un binario de `api.github.com` al resolver la config. Vitest no arranca sin red a GitHub (403 por rate-limit reproducido). Dependencia de red externa en herramientas de test/build. | **Media** | `vite.config.ts:6` |
| A5 | `docs/architecture.md` **desactualizado respecto a toda la Operación Remake**: 0 menciones a `cognition/`, referencia 4 archivos de `frontend/src/` eliminados, describe parámetros de personalidad ya inexistentes. Es el documento de entrada para un lector nuevo. | **Media** | `docs/architecture.md:110-111,203-204`; último commit anterior a Remake |
| A6 | `except Exception: pass` alrededor de `path.unlink()` en `routes_files.py` (líneas ~186, ~218): si el borrado físico falla, **se borra igualmente la fila de DB** → archivo huérfano en disco sin registro ni log. Contradice la garantía "DB + disco sincronizados" del diseño del Paso 3. | **Baja** | `routes_files.py:183-188, 215-220` |
| A7 | 9 usos directos de `datetime.utcnow()` en 3 archivos de producción pese a existir `utc_now()`. Deprecado en Python 3.12+; mezclar naive/aware es fuente de `TypeError` en comparaciones. | **Baja** | `grep utcnow() backend/app` |
| A8 | Proxy de desarrollo (`vite.config.ts`) no incluye `/uploads` ni `/files`: en `npm run dev` las imágenes subidas y la gestión de archivos no funcionan (mismo patrón del bug de Caddy `/uploads*` ya corregido en producción). | **Baja** | `vite.config.ts` bloque `proxy` |
| A9 | Flaky `test_daily_max_hit_returns_rate_limited` documentado desde 2026-08-24, nunca resuelto de raíz (contaminación de orden por `cooldown_active`). No falló en esta pasada (intermitente). | **Baja** | `docs/state.md` "Tests flaky conocidos" |
| A10 | Sin cabeceras de seguridad HTTP en `Caddyfile.example` (HSTS, `X-Frame-Options`, `X-Content-Type-Options`). | **Baja** | `deploy/caddy/Caddyfile.example` |
| A11 | `refusal-mode-architecture.md` contiene 8 menciones a `refusal_chance` (sustituido por `refusal_propensity` en Fase 1). Pendiente confirmar si se presenta como histórico o como vigente. | **A verificar** | `docs/refusal-mode-architecture.md` |

### Recomendaciones priorizadas

1. **A2 — Rate-limit en `/auth/login` y reset** (reutilizar el patrón de `GuestIPRateLimiter`
   por IP + email) y hacer que reCAPTCHA **falle cerrado** en producción (bypass solo si
   `SITY_ENV=dev` explícito). Leer `RECAPTCHA_SECRET_KEY` en tiempo de petición, no en import.
2. **A1 — Autenticación en `GET /uploads/images/{filename}`**: `Depends(get_current_user)` +
   comprobar que `FileArtifact.user_id` coincide (para Guest: `user_id IS NULL` y misma
   sesión, o servir solo vía token firmado de corta duración). Mismo criterio de 404 opaco que
   `DELETE /files/{id}`.
3. **A3 + A4 juntos** — `mkcert()` condicionado a `command === 'serve'` (2 líneas) y añadir
   `npm test` al job `mobile` del CI. Coste mínimo, cierra dos huecos a la vez.
4. **A5 — Reescribir `docs/architecture.md`** como visión actual: `cognition/` como núcleo,
   enlazando al mapa maestro `docs/remake/pipeline-cognitivo-completo.md`; eliminar
   referencias a `frontend/`. Confirmar A11 en la misma pasada.
5. **A6 + A7 + A8** — pasada de mantenimiento pequeña: `WARN` en los `unlink` fallidos (y
   decidir si abortar el `db.delete`), unificar `utcnow()` → `utc_now()`, añadir `/uploads` y
   `/files` al proxy de dev.
6. **A9 + A10** — cuando haya sesión de mantenimiento: teardown de `cooldown_active` en
   `TestEvaluatorRateLimits`; bloque `header` en Caddy.

### Límites de esta pasada (no verificado)

- **Logs de producción** y **base de datos real** (viven en la Raspberry Pi; esta revisión se
  hizo sobre el clon del repositorio). Consistencia de `module=` en logs solo verificada por
  lectura de código, no sobre `app-*.jsonl` reales.
- **CI de GitHub** no consultado con `gh run list` (herramienta no disponible en este
  entorno). Se ejecutaron ambas suites localmente con la configuración del CI como
  sustituto.
- **Pruebas ofensivas activas** (fuerza bruta real contra login, intento de acceso a
  `/uploads/images/` de otro usuario en producción): omitidas por diseño pasivo de esta
  auditoría y para no activar guardarraíles. A1 y A2 quedan confirmados por lectura de
  código, no por explotación — Alex puede verificar A1 manualmente abriendo la URL de una
  imagen en una ventana de incógnito sin sesión.
