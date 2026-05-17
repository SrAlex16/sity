import json
from typing import Any

from sqlmodel import Session, select

from app.memory.models import Setting, utc_now
from app.settings.config_loader import load_default_config


PERSONALITY_KEYS = {
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "tsundere_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
    "melancholy_level",
}


def clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


class SettingsService:
    def __init__(self, session: Session):
        self.session = session

    def get_all_settings(self) -> dict[str, Any]:
        config = load_default_config()

        stored_settings = self.session.exec(select(Setting)).all()
        for row in stored_settings:
            # Ignore old deprecated personality keys if they still exist in SQLite.
            if row.key in {
                "personality.glados_mode",
                "personality.autonomy_level",
                "personality.proactivity_level",
            }:
                continue

            self._set_nested(config, row.key, json.loads(row.value_json))

        return config

    def get_personality(self) -> dict[str, float]:
        settings = self.get_all_settings()
        personality = settings.get("personality", {})
        return {key: float(personality[key]) for key in PERSONALITY_KEYS if key in personality}

    def adjust_personality(
        self,
        parameter: str,
        operation: str,
        amount: float,
        source: str = "ui",
    ) -> tuple[float, float]:
        if parameter not in PERSONALITY_KEYS:
            raise ValueError(f"Unknown personality parameter: {parameter}")

        personality = self.get_personality()
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
        self.set_setting(f"personality.{parameter}", new_value, source=source)

        return old_value, new_value

    def set_setting(self, key: str, value: Any, source: str = "ui") -> None:
        existing = self.session.exec(select(Setting).where(Setting.key == key)).first()
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
                    created_at=now,
                    updated_at=now,
                )
            )

        self.session.commit()

    @staticmethod
    def _set_nested(target: dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        cursor = target

        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})

        cursor[parts[-1]] = value
