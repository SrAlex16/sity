from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlmodel import Session

from app.auth.dependencies import CurrentUser, get_current_user

def _require_non_guest(current: CurrentUser) -> CurrentUser:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    return current
from app.memory.db import get_session
from app.settings.alter_service import AlterService
from app.settings.schemas import (
    AlterSlot,
    LanguageSettings,
    LocationSettings,
    PersonalityAdjustRequest,
    PersonalityAdjustResponse,
    PersonalitySettings,
    RenameAlterRequest,
    SaveAlterRequest,
    SUPPORTED_LANGUAGE_CODES,
    VoiceSettings,
)
from app.initiative.settings import (
    InitiativeSettings,
    get_initiative_settings,
    set_initiative_settings,
)
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log

_SLOT = Path(ge=1, le=5, description="Slot number (1–5)")


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    service = SettingsService(session)
    return service.get_all_settings(session_id=current.session_id)


@router.get("/personality")
def get_personality(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    service = SettingsService(session)
    return service.get_personality(session_id=current.session_id)


@router.post("/personality/adjust", response_model=PersonalityAdjustResponse)
def adjust_personality(
    request: PersonalityAdjustRequest,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    trace_id = new_trace_id()
    service = SettingsService(session)

    try:
        old_value, new_value = service.adjust_personality(
            parameter=request.parameter,
            operation=request.operation,
            amount=request.amount,
            source=request.source,
            session_id=current.session_id,
        )
    except ValueError as exc:
        write_log(
            level="WARN",
            module="settings",
            event="setting_update_rejected",
            trace_id=trace_id,
            payload={
                "parameter": request.parameter,
                "operation": request.operation,
                "amount": request.amount,
                "reason": str(exc),
            },
            audit=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_log(
        level="AUDIT",
        module="settings",
        event="personality_setting_updated",
        trace_id=trace_id,
        payload={
            "parameter": request.parameter,
            "operation": request.operation,
            "amount": request.amount,
            "old_value": old_value,
            "new_value": new_value,
            "source": request.source,
        },
        audit=True,
    )

    message = (
        f"{request.parameter} actualizado de {round(old_value * 100)}% "
        f"a {round(new_value * 100)}%. Una calibración cuestionable, pero aceptada."
    )

    from app.achievements.triggers.inline import fire as _fire_ach
    if current.user_id is not None:
        _fire_ach(session, current.session_id, "persona")

    return PersonalityAdjustResponse(
        ok=True,
        parameter=request.parameter,
        old_value=old_value,
        new_value=new_value,
        message=message,
    )


@router.post("/personality/reset", response_model=PersonalitySettings)
def reset_personality(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Remove session personality overrides, falling back to the global default.

    Accessible to all roles — each session resets its own overrides only.
    """
    service = SettingsService(session)
    return service.reset_personality(session_id=current.session_id, source="ui")


@router.get("/voice", response_model=VoiceSettings)
def get_voice_settings(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Per-session voice settings (mode/transcript/long_response) with global fallback.
    audio_cleanup_days is always read from the global admin row."""
    _require_non_guest(current)
    return SettingsService(session).get_voice_settings(session_id=current.session_id)


@router.put("/voice", response_model=VoiceSettings)
def update_voice_settings(
    settings: VoiceSettings,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Save per-session voice settings. audio_cleanup_days is only persisted by admin."""
    _require_non_guest(current)
    return SettingsService(session).set_voice_settings(
        settings, session_id=current.session_id, is_admin=current.is_admin
    )


@router.get("/language", response_model=LanguageSettings)
def get_language_settings(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Per-session language override for Sity's conversation language."""
    _require_non_guest(current)
    override = SettingsService(session).get_language_override(session_id=current.session_id)
    return LanguageSettings(language_override=override)


@router.put("/language", response_model=LanguageSettings)
def update_language_settings(
    body: LanguageSettings,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Save per-session language override."""
    _require_non_guest(current)
    if body.language_override not in SUPPORTED_LANGUAGE_CODES:
        raise HTTPException(status_code=422, detail=f"Código de idioma no soportado: {body.language_override!r}")
    SettingsService(session).set_language_override(
        value=body.language_override,
        session_id=current.session_id,
    )
    return LanguageSettings(language_override=body.language_override)


# ---------------------------------------------------------------------------
# Location settings — per-session
# ---------------------------------------------------------------------------

_VALID_LOCATION_SOURCES = frozenset({"manual", "browser", "auto", "denied", ""})


@router.get("/location", response_model=LocationSettings)
def get_location_settings_endpoint(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Per-session location (city + source) used by Sity for local context."""
    _require_non_guest(current)
    return SettingsService(session).get_location_settings(session_id=current.session_id)


@router.put("/location", response_model=LocationSettings)
def update_location_settings_endpoint(
    body: LocationSettings,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Save per-session location settings."""
    _require_non_guest(current)
    if body.source not in _VALID_LOCATION_SOURCES:
        raise HTTPException(status_code=422, detail=f"Fuente de ubicación no válida: {body.source!r}")
    return SettingsService(session).set_location_settings(body, session_id=current.session_id)


# ---------------------------------------------------------------------------
# Initiative settings — proactive messaging toggles (User/Admin only)
# ---------------------------------------------------------------------------

@router.get("/initiative", response_model=InitiativeSettings)
def get_initiative_settings_endpoint(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Per-session initiative settings with global fallback."""
    _require_non_guest(current)
    return get_initiative_settings(session, session_id=current.session_id)


@router.put("/initiative", response_model=InitiativeSettings)
def update_initiative_settings_endpoint(
    body: InitiativeSettings,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Save per-session initiative settings."""
    _require_non_guest(current)
    return set_initiative_settings(session, body, session_id=current.session_id)


# ---------------------------------------------------------------------------
# Personality Alters — saved presets (5 slots per user)
# ---------------------------------------------------------------------------

@router.get("/alters", response_model=list[AlterSlot])
def list_alters(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    return AlterService(session).list_alters(user_id=current.user_id)


@router.post("/alters/{slot}/save", response_model=AlterSlot)
def save_alter(
    body: SaveAlterRequest,
    slot: int = _SLOT,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    return AlterService(session).save_alter(
        user_id=current.user_id,
        slot=slot,
        name=body.name,
        current_session_id=current.session_id,
    )


@router.post("/alters/{slot}/load")
def load_alter(
    slot: int = _SLOT,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    try:
        personality = AlterService(session).load_alter(
            user_id=current.user_id,
            slot=slot,
            session_id=current.session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"personality": personality}


@router.patch("/alters/{slot}/rename")
def rename_alter(
    body: RenameAlterRequest,
    slot: int = _SLOT,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    try:
        AlterService(session).rename_alter(
            user_id=current.user_id,
            slot=slot,
            new_name=body.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/alters/{slot}", status_code=204)
def clear_alter(
    slot: int = _SLOT,
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    AlterService(session).clear_alter(user_id=current.user_id, slot=slot)


@router.post("/alters/{from_slot}/copy/{to_slot}", response_model=AlterSlot)
def copy_alter(
    from_slot: int = Path(ge=1, le=5, description="Source slot (1–5)"),
    to_slot: int = Path(ge=1, le=5, description="Destination slot (1–5)"),
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    _require_non_guest(current)
    assert current.user_id is not None
    try:
        return AlterService(session).copy_alter(
            user_id=current.user_id,
            from_slot=from_slot,
            to_slot=to_slot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# UI language suggestion — Sistema 1
# ---------------------------------------------------------------------------

# Spanish-speaking countries (Spain + all LatAm)
_COUNTRY_TO_UI_LANG: dict[str, str] = {
    "ES": "es",
    "MX": "es", "CO": "es", "AR": "es", "PE": "es", "VE": "es",
    "CL": "es", "EC": "es", "GT": "es", "CU": "es", "BO": "es",
    "DO": "es", "HN": "es", "PY": "es", "SV": "es", "NI": "es",
    "CR": "es", "PA": "es", "UY": "es", "GQ": "es", "PR": "es",
    # English
    "US": "en", "GB": "en", "AU": "en", "CA": "en", "NZ": "en",
    "IE": "en", "ZA": "en", "SG": "en", "PH": "en", "IN": "en",
    "NG": "en", "GH": "en", "KE": "en",
    # Japanese
    "JP": "ja",
    # Future expansions — mapped but not yet in UI_LANG_SUPPORTED; fall back to "en"
    "FR": "fr", "BE": "fr", "CH": "fr",
    "DE": "de", "AT": "de",
    "BR": "pt", "PT": "pt",
    "IT": "it",
}

# Only these have translations in the frontend; others fall back to "en"
_UI_LANG_SUPPORTED = frozenset({"es", "en", "ja"})
_UI_LANG_DEFAULT = "en"


@router.get("/ui-language-suggestion")
def get_ui_language_suggestion(request: Request) -> dict:
    """Return a UI language suggestion based on Cloudflare CF-IPCountry header.

    No auth required — called by the frontend before any login, also for guests.
    Logs the raw CF-IPCountry value so it can be verified in journalctl/app logs.
    """
    country = request.headers.get("cf-ipcountry", "").strip().upper()
    mapped = _COUNTRY_TO_UI_LANG.get(country, _UI_LANG_DEFAULT)
    lang = mapped if mapped in _UI_LANG_SUPPORTED else _UI_LANG_DEFAULT

    write_log(
        level="INFO",
        module="settings",
        event="ui_language_suggestion",
        payload={"cf_ipcountry": country or None, "mapped_lang": mapped, "suggested_lang": lang},
    )
    return {"lang": lang, "country": country or None}
