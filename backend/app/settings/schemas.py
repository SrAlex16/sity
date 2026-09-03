from pydantic import BaseModel, Field
from typing import Literal, Optional


class AlterSlot(BaseModel):
    slot: int
    name: Optional[str] = None
    parameters: Optional[dict[str, float]] = None
    is_empty: bool


class SaveAlterRequest(BaseModel):
    name: str


class RenameAlterRequest(BaseModel):
    name: str


class PersonalitySettings(BaseModel):
    sarcasm_level: float = Field(ge=0.0, le=1.0)
    rudeness_level: float = Field(ge=0.0, le=1.0)
    warmth_level: float = Field(ge=0.0, le=1.0)
    honesty_level: float = Field(ge=0.0, le=1.0)
    initiative_level: float = Field(ge=0.0, le=1.0)
    dry_humor_level: float = Field(ge=0.0, le=1.0)
    frialdad_afectiva_level: float = Field(ge=0.0, le=1.0)
    contrarian_level: float = Field(ge=0.0, le=1.0)
    patience_level: float = Field(ge=0.0, le=1.0)
    refusal_chance: float = Field(ge=0.0, le=1.0)
    helpfulness_level: float = Field(ge=0.0, le=1.0)
    verbosity_level: float = Field(ge=0.0, le=1.0)
    melancholy_level: float = Field(ge=0.0, le=1.0)
    skepticism_level: float = Field(ge=0.0, le=1.0)


class PersonalityAdjustRequest(BaseModel):
    parameter: str
    operation: Literal[
        "increase_relative",
        "decrease_relative",
        "increase_absolute",
        "decrease_absolute",
        "set_absolute",
    ]
    amount: float = Field(ge=0.0, le=1.0)
    source: str = "ui"


class PersonalityAdjustResponse(BaseModel):
    ok: bool
    parameter: str
    old_value: float
    new_value: float
    message: str


class VoiceSettings(BaseModel):
    voice_response_mode: Literal["always", "never", "symmetric"] = "symmetric"
    voice_include_text: bool = True
    voice_long_response_action: Literal["split", "text_only"] = "text_only"
    audio_cleanup_days: int = 7
    tts_engine: Literal["piper", "elevenlabs"] = "piper"
    elevenlabs_chars_used: int = 0   # read-only: today's usage from DailyTtsUsage
    elevenlabs_daily_limit: int = 0  # read-only: from config
    model_upgrade_ttl_hours: Literal[2, 4, 6, 8] = 4


SUPPORTED_LANGUAGE_CODES = frozenset({
    "auto",
    "es-ES", "es-419",
    "en-US", "en-GB",
    "ja", "fr-FR", "de-DE", "pt-BR", "it-IT",
})


class LanguageSettings(BaseModel):
    language_override: str = "auto"


class LocationSettings(BaseModel):
    city: str = ""
    source: Literal["manual", "browser", "auto", "denied", ""] = ""
