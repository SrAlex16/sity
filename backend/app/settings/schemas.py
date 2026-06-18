from pydantic import BaseModel, Field
from typing import Literal, Optional


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
