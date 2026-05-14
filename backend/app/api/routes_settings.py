from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.memory.db import get_session
from app.settings.schemas import PersonalityAdjustRequest, PersonalityAdjustResponse
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    service = SettingsService(session)
    return service.get_all_settings()


@router.get("/personality")
def get_personality(session: Session = Depends(get_session)):
    service = SettingsService(session)
    return service.get_personality()


@router.post("/personality/adjust", response_model=PersonalityAdjustResponse)
def adjust_personality(
    request: PersonalityAdjustRequest,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()
    service = SettingsService(session)

    try:
        old_value, new_value = service.adjust_personality(
            parameter=request.parameter,
            operation=request.operation,
            amount=request.amount,
            source=request.source,
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
