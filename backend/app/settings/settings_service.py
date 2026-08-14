import json
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.memory.models import Setting, utc_now
from app.settings.config_loader import load_default_config
from app.settings.schemas import VoiceSettings


PERSONALITY_KEYS = {
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "frialdad_afectiva_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
    "melancholy_level",
    "skepticism_level",
}

CANONICAL_PERSONALITY: dict[str, float] = {
    "sarcasm_level":             0.25,
    "rudeness_level":            0.15,
    "warmth_level":              0.35,
    "honesty_level":             0.90,
    "initiative_level":          0.05,
    "dry_humor_level":           0.30,
    "melancholy_level":          0.15,
    "frialdad_afectiva_level":   0.20,
    "contrarian_level":          0.10,
    "patience_level":            0.65,
    "refusal_chance":            0.15,
    "helpfulness_level":         0.60,
    "verbosity_level":           0.35,
    "skepticism_level":          0.20,
}

_DEPRECATED_KEYS = frozenset({
    "personality.glados_mode",
    "personality.autonomy_level",
    "personality.proactivity_level",
})


def clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


class SettingsService:
    def __init__(self, session: Session):
        self.session = session

    # ── Global settings view (for admin endpoints / GET /settings) ────────────

    def get_all_settings(self, session_id: Optional[str] = None) -> dict[str, Any]:
        """Return merged config: defaults → global DB rows → session overrides."""
        config = load_default_config()

        global_rows = self.session.exec(
            select(Setting).where(col(Setting.session_id).is_(None))
        ).all()
        for row in global_rows:
            if row.key in _DEPRECATED_KEYS:
                continue
            self._set_nested(config, row.key, json.loads(row.value_json))

        if session_id is not None:
            session_rows = self.session.exec(
                select(Setting).where(Setting.session_id == session_id)
            ).all()
            for row in session_rows:
                if row.key in _DEPRECATED_KEYS:
                    continue
                self._set_nested(config, row.key, json.loads(row.value_json))

        return config

    # ── Personality — session-isolated ────────────────────────────────────────

    def get_personality(self, session_id: Optional[str] = None) -> dict[str, float]:
        """Return personality dict: global defaults overlaid by session-specific values."""
        settings = self.get_all_settings(session_id=session_id)
        personality = settings.get("personality", {})
        return {key: float(personality[key]) for key in PERSONALITY_KEYS if key in personality}

    def adjust_personality(
        self,
        parameter: str,
        operation: str,
        amount: float,
        source: str = "ui",
        session_id: Optional[str] = None,
    ) -> tuple[float, float]:
        if parameter not in PERSONALITY_KEYS:
            raise ValueError(f"Unknown personality parameter: {parameter}")

        personality = self.get_personality(session_id=session_id)
        old_value = float(personality[parameter])

        if operation == "increase_relative":
            new_value = old_value + (old_value * amount)
        elif operation == "decrease_relative":
            new_value = old_value - (old_value * amount)
        elif operation == "increase_absolute":
            new_value = old_value + amount
        elif operation == "decrease_absolute":
            new_value = old_value - amount
        elif operation == "set_absolute":
            new_value = amount
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        new_value = clamp_01(round(new_value, 4))
        self.set_setting(f"personality.{parameter}", new_value, source=source, session_id=session_id)

        return old_value, new_value

    def reset_personality(
        self,
        session_id: Optional[str] = None,
        source: str = "ui",
    ) -> dict[str, float]:
        """Reset personality for a session or for the global fallback.

        session_id is not None → delete session overrides (falls back to global).
        session_id is None     → rewrite global rows with canonical values.
        """
        if session_id is not None:
            session_rows = self.session.exec(
                select(Setting).where(
                    Setting.session_id == session_id,
                    col(Setting.key).like("personality.%"),
                )
            ).all()
            for row in session_rows:
                self.session.delete(row)
            self.session.commit()
        else:
            for key, value in CANONICAL_PERSONALITY.items():
                self.set_setting(f"personality.{key}", value, source=source, session_id=None)

        return self.get_personality(session_id=session_id)

    # ── Generic setting write — session-aware ─────────────────────────────────

    def set_setting(
        self,
        key: str,
        value: Any,
        source: str = "ui",
        session_id: Optional[str] = None,
    ) -> None:
        if session_id is None:
            existing = self.session.exec(
                select(Setting).where(
                    Setting.key == key,
                    col(Setting.session_id).is_(None),
                )
            ).first()
        else:
            existing = self.session.exec(
                select(Setting).where(
                    Setting.key == key,
                    Setting.session_id == session_id,
                )
            ).first()

        now = utc_now()
        if existing:
            existing.value_json = json.dumps(value)
            existing.source = source
            existing.updated_at = now
            self.session.add(existing)
        else:
            self.session.add(
                Setting(
                    key=key,
                    value_json=json.dumps(value),
                    source=source,
                    session_id=session_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        self.session.commit()

    # ── Voice settings ─────────────────────────────────────────────────────────
    # Per-session keys: read from session row first, fall back to global default.
    # Admin-only key: audio_cleanup_days — always global (session_id=NULL).

    _VOICE_PER_SESSION = ("voice_response_mode", "voice_include_text", "voice_long_response_action")
    _VOICE_ADMIN_GLOBAL = ("audio_cleanup_days",)

    def get_voice_settings(self, session_id: Optional[str] = None) -> VoiceSettings:
        defaults = VoiceSettings()
        data: dict[str, Any] = {}

        for key in self._VOICE_PER_SESSION:
            row = None
            if session_id is not None:
                row = self.session.exec(
                    select(Setting).where(
                        Setting.key == f"voice.{key}",
                        Setting.session_id == session_id,
                    )
                ).first()
            if row is None:
                row = self.session.exec(
                    select(Setting).where(
                        Setting.key == f"voice.{key}",
                        col(Setting.session_id).is_(None),
                    )
                ).first()
            if row is not None:
                data[key] = json.loads(row.value_json)

        for key in self._VOICE_ADMIN_GLOBAL:
            row = self.session.exec(
                select(Setting).where(
                    Setting.key == f"voice.{key}",
                    col(Setting.session_id).is_(None),
                )
            ).first()
            if row is not None:
                data[key] = json.loads(row.value_json)

        return VoiceSettings(**{**defaults.model_dump(), **data})

    def set_voice_settings(
        self,
        settings: VoiceSettings,
        session_id: Optional[str] = None,
        is_admin: bool = False,
        source: str = "ui",
    ) -> VoiceSettings:
        for key in self._VOICE_PER_SESSION:
            self.set_setting(f"voice.{key}", getattr(settings, key), source=source, session_id=session_id)
        if is_admin:
            self.set_setting("voice.audio_cleanup_days", settings.audio_cleanup_days, source=source, session_id=None)
        return self.get_voice_settings(session_id=session_id)

    # ── Language override ──────────────────────────────────────────────────────
    # Per-session: session row first, fall back to global, then default "auto".

    def get_language_override(self, session_id: Optional[str] = None) -> str:
        row = None
        if session_id is not None:
            row = self.session.exec(
                select(Setting).where(
                    Setting.key == "language.override",
                    Setting.session_id == session_id,
                )
            ).first()
        if row is None:
            row = self.session.exec(
                select(Setting).where(
                    Setting.key == "language.override",
                    col(Setting.session_id).is_(None),
                )
            ).first()
        return str(json.loads(row.value_json)) if row is not None else "auto"

    def set_language_override(
        self,
        value: str,
        session_id: Optional[str] = None,
        source: str = "ui",
    ) -> str:
        self.set_setting("language.override", value, source=source, session_id=session_id)
        return self.get_language_override(session_id=session_id)

    # ── Bulk personality write — used by AlterService.load_alter ──────────────

    def set_all_personality(self, session_id: str, values: dict[str, float]) -> dict[str, float]:
        """Overwrite all 15 personality parameters for a session at once.

        Validates every key, clamps to [0, 1], and commits via set_setting so the
        session-isolation chain (session row → global fallback) is respected.
        Does NOT modify any other session or global rows.
        """
        unknown = set(values.keys()) - PERSONALITY_KEYS
        if unknown:
            raise ValueError(f"Unknown personality parameters: {unknown}")
        missing = PERSONALITY_KEYS - set(values.keys())
        if missing:
            raise ValueError(f"Missing personality parameters: {missing}")
        for key, value in values.items():
            self.set_setting(
                f"personality.{key}",
                clamp_01(round(float(value), 4)),
                source="alter",
                session_id=session_id,
            )
        return self.get_personality(session_id=session_id)

    @staticmethod
    def _set_nested(target: dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        cursor = target

        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})

        cursor[parts[-1]] = value
