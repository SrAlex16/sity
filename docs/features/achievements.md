# Achievements / Sistema de Logros

[English](#english) · [Español](#español)

---

## English

### Overview

Sity has a declarative achievement system. Adding a new achievement means adding an entry to `achievements/catalog.py` and a new trigger only if needed. The main conversation model is completely unaware of the achievement system — pattern detection for secret achievements uses separate Haiku calls.

### Architecture

```
catalog.py      ← declarative achievement definitions
engine.py       ← try_unlock_achievement (never raises exceptions)
triggers/       ← inline, post-turn, and background triggers
endpoints.py    ← GET /achievements (no auth required)
```

### Data model

`UserAchievement` table: `user_id` · `slug` · `unlocked_at`

Unique constraint on `(user_id, slug)`. Only authenticated users have rows — guests never unlock achievements.

### Categories

| Category | Examples |
|---|---|
| Personality | Unlocked through specific trait configurations |
| Tools | Using integrations (Spotify, HA, Calendar) |
| Memory | Long-term interactions, milestones |
| Secret | Detected via pattern analysis (Haiku), hidden until unlocked |
| Home automation | HA-specific actions |
| Background | Triggered by background daemons |

### Trigger types

- **Inline** (21 triggers in Phase 2a): checked during the turn itself
- **Post-turn**: checked after the turn completes
- **Background**: triggered by daemons (social job, episode synthesis, etc.)

### Engine rules

- `try_unlock_achievement` never raises exceptions — achievement failures are always logged, never surfaced
- `get_user_achievements` hides secret achievements until the user has unlocked at least one secret
- Unknown slugs are logged as `achievement_slug_unknown` at WARN level (not silently dropped)

### Configuration

Thresholds live in `config/default_config.yaml` under `achievements:`. No hardcoded values in code.

### How to add an achievement

1. Add entry to `achievements/catalog.py`
2. If it needs a new trigger type, create the trigger and connect it to the integration point
3. Write tests in `tests/test_achievement_triggers.py`
4. Add config key in `default_config.yaml` if threshold is configurable

---

## Español

### Visión general

Sistema de logros declarativo. Añadir un logro = añadir una entrada en `achievements/catalog.py`. El modelo de conversación principal desconoce completamente el sistema de logros — la detección de patrones para logros secretos usa llamadas separadas a Haiku.

### Arquitectura

Ver diagrama en la sección en inglés.

### Modelo de datos

Tabla `UserAchievement`: `user_id` · `slug` · `unlocked_at`. Restricción UNIQUE en `(user_id, slug)`. Solo usuarios autenticados — los guest nunca desbloquean logros.

### Categorías

Personalidad · Tools · Memoria · Secretos · Domótica · Background. Ver tabla en la sección en inglés.

### Reglas del motor

- `try_unlock_achievement` nunca lanza excepciones
- `get_user_achievements` oculta los logros secretos hasta que el usuario haya desbloqueado al menos uno
- Slugs desconocidos: log `achievement_slug_unknown` en WARN (no se descartan silenciosamente)

### Umbrales en config

Los umbrales viven en `config/default_config.yaml` bajo `achievements:`. Sin valores hardcodeados en código.

### Cómo añadir un logro

1. Añadir entrada en `achievements/catalog.py`
2. Si necesita nuevo tipo de trigger, crear el trigger y conectarlo al punto de integración
3. Escribir tests en `tests/test_achievement_triggers.py`
4. Añadir clave en `default_config.yaml` si el umbral es configurable
