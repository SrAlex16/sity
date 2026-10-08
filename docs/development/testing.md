# Testing / Tests

[English](#english) · [Español](#español)

---

## English

### Current state (2026-10-08)

| Metric | Value |
|---|---|
| Backend tests passing | 3,704 (6 skipped) |
| Global coverage | 73% |
| mypy errors | 0 |
| Frontend tests (vitest) | 12/12 |

### Running tests

```bash
# Backend (from project root, in virtualenv)
pytest

# With coverage
pytest --cov=backend/app --cov-report=term-missing

# Type checking
mypy backend/app/

# Frontend
cd mobile/
npm test
```

### Test organization

```
tests/
  test_session_queue.py       16 tests — turn serialization, versioning
  test_timers.py              28 tests — timer/alarm lifecycle
  test_achievement_triggers.py  coverage for all achievement trigger types
  test_response_integrity.py  31 tests — capability claims, leaks, fabrication
  test_tool_executor.py       3 tests — unknown tool sanitization
  test_semantic_service.py    29 tests — SemanticFact lifecycle
  test_reflection_semantic_context.py  10 tests
  test_decision_service.py    52 tests — utility formula, pipeline
  cognition/
    test_perception.py
    test_appraisal.py
    test_episode_service.py   29 tests
    test_autobiographical.py  17 tests
    test_reflection.py        (Phase 6: 25 tests)
    test_values.py            (Phase 6: 21 tests)
    test_metacognition.py     (Phase 6: 19 tests)
    test_procedural_service.py  53 tests
  social/
    test_social_update.py
    test_social_recall.py
    test_social_reflection.py 8 tests
    test_initiative.py        128 tests (4 phases)
```

### Behavioral regression suite

A separate suite that calls the real Haiku model. Excluded from normal CI (requires `ANTHROPIC_API_KEY`).

```bash
pytest tests/behavioral/ -m behavioral
```

Expected results: 9 passed, 1 xfailed.

### CI (GitHub Actions)

- Backend suite runs on every push
- CI isolates backend from real API keys (mock provider)
- Frontend tests do not yet run in CI (open finding A3 from 2026-09-16 audit)

### Known issues

- One flaky test (unresolved, tracked)
- `vite-plugin-mkcert` loads unconditionally — Vitest fails without network access to GitHub. Fix: make it conditional on environment. (Open finding A4)

### Testing conventions

- Mock provider for all AI calls in unit tests (deterministic, no API key needed)
- Each cognition module tested in isolation with known inputs
- Integration points tested with full pipeline mocks
- Social and memory tables tested with separate test database instances
- Authentication tested with both valid and invalid JWT tokens

---

## Español

### Estado actual (2026-10-08)

Ver tabla en la sección en inglés.

### Ejecutar tests

```bash
pytest                                        # backend (en virtualenv)
pytest --cov=backend/app --cov-report=term-missing
mypy backend/app/
cd mobile/ && npm test                        # frontend
```

### Suite de regresión conductual

Suite separada que llama al modelo real Haiku. Excluida del CI normal (requiere `ANTHROPIC_API_KEY`).

```bash
pytest tests/behavioral/ -m behavioral
```

Resultado esperado: 9 passed, 1 xfailed.

### CI (GitHub Actions)

- Suite de backend corre en cada push
- CI aísla el backend de las keys API reales (proveedor mock)
- Los tests de frontend no corren en CI aún (hallazgo A3 de auditoría 2026-09-16)

### Issues conocidos

- Un test flaky sin resolver
- `vite-plugin-mkcert` se carga incondicionalmente — Vitest falla sin acceso de red a GitHub (hallazgo A4 — fix pendiente: condicionarlo al entorno)

### Convenciones de test

- Proveedor mock para todas las llamadas de IA en tests unitarios (determinista, sin key API)
- Cada módulo cognitivo probado en aislamiento con inputs conocidos
- Tablas de memoria y social probadas con instancias de DB de test separadas
- Autenticación probada con tokens JWT válidos e inválidos
