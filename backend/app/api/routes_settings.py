from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth.dependencies import CurrentUser, get_current_user, require_admin

def _require_non_guest(current: CurrentUser) -> CurrentUser:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    return current
from app.memory.db import get_session
from app.settings.schemas import PersonalityAdjustRequest, PersonalityAdjustResponse, PersonalitySettings, VoiceSettings
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log


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
