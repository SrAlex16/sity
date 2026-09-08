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
    warmth:              float = Field(ge=0.0, le=1.0)
    empathy:             float = Field(ge=0.0, le=1.0)
    directness:          float = Field(ge=0.0, le=1.0)
    assertiveness:       float = Field(ge=0.0, le=1.0)
    independence:        float = Field(ge=0.0, le=1.0)
    skepticism:          float = Field(ge=0.0, le=1.0)
    patience:            float = Field(ge=0.0, le=1.0)
    curiosity:           float = Field(ge=0.0, le=1.0)
    proactivity:         float = Field(ge=0.0, le=1.0)
    helpfulness:         float = Field(ge=0.0, le=1.0)
    honesty:             float = Field(ge=0.0, le=1.0)
    playfulness:         float = Field(ge=0.0, le=1.0)
    emotional_stability: float = Field(ge=0.0, le=1.0)


class CommunicationPreferences(BaseModel):
    verbosity: float = Field(default=0.60, ge=0.0, le=1.0)


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
