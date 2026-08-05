"""Handlers for timer/alarm tools: set_timer, set_alarm, list_timers, cancel_timer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.timers.service import cancel_task, create_scheduled_task, list_pending
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_DEFAULT_TIMER_MSG = "Se acabó tu temporizador."
_DEFAULT_ALARM_MSG = "Es la hora del recordatorio que configuraste."


def _ok(tool_name: str, text: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=True,
        message=text,
        updated_parameters=[],
        raw_result={"success": True, "text": text, "local_final": True},
    )


def _err(tool_name: str, text: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=False,
        message=text,
        updated_parameters=[],
        raw_result={"success": False, "text": text, "local_final": True},
    )


@tool_handler("set_timer")
def handle_set_timer(ctx: ToolContext) -> ToolExecutionResult:
    duration_seconds = ctx.tool_input.get("duration_seconds")
    message = str(ctx.tool_input.get("message") or _DEFAULT_TIMER_MSG).strip()
    session_id = ctx.executor.session_id
    db_session = ctx.executor.session

    if not isinstance(duration_seconds, int) or duration_seconds < 1:
        return _err("set_timer", "duration_seconds debe ser un entero positivo.")

    fires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    try:
        task = create_scheduled_task(
            db_session=db_session,
            session_id=session_id,
            fires_at=fires_at,
            message=message,
        )
    except ValueError as exc:
        return _err("set_timer", str(exc))

    mins = duration_seconds // 60
    secs = duration_seconds % 60
    if mins and secs:
        human = f"{mins} min {secs} s"
    elif mins:
        human = f"{mins} min"
    else:
        human = f"{secs} s"

    text = (
        f"Temporizador de {human} configurado. "
        f"ID: {task.id}. "
        f"Te avisare a las {fires_at.strftime('%H:%M:%S')} UTC."
    )
    return _ok("set_timer", text)


@tool_handler("set_alarm")
def handle_set_alarm(ctx: ToolContext) -> ToolExecutionResult:
    fires_at_str = str(ctx.tool_input.get("fires_at", "")).strip()
    message = str(ctx.tool_input.get("message") or _DEFAULT_ALARM_MSG).strip()
    session_id = ctx.executor.session_id
    db_session = ctx.executor.session

    if not fires_at_str:
        return _err("set_alarm", "fires_at es obligatorio.")

    try:
        fires_at = datetime.fromisoformat(fires_at_str)
    except ValueError:
        return _err("set_alarm", f"Formato de fecha no válido: '{fires_at_str}'. Usa ISO 8601.")

    if fires_at.tzinfo is None:
        fires_at = fires_at.replace(tzinfo=timezone.utc)
    fires_at = fires_at.astimezone(timezone.utc)

    try:
        task = create_scheduled_task(
            db_session=db_session,
            session_id=session_id,
            fires_at=fires_at,
            message=message,
        )
    except ValueError as exc:
        return _err("set_alarm", str(exc))

    text = (
        f"Alarma configurada para las {fires_at.strftime('%H:%M:%S')} UTC "
        f"({fires_at_str}). ID: {task.id}."
    )
    return _ok("set_alarm", text)


@tool_handler("list_timers")
def handle_list_timers(ctx: ToolContext) -> ToolExecutionResult:
    session_id = ctx.executor.session_id
    db_session = ctx.executor.session

    tasks = list_pending(db_session, session_id)
    if not tasks:
        return _ok("list_timers", "No tienes temporizadores activos.")

    lines = ["Temporizadores activos:"]
    now = datetime.now(timezone.utc)
    for t in tasks:
        fa = t.fires_at
        if fa.tzinfo is None:
            fa = fa.replace(tzinfo=timezone.utc)
        remaining = fa - now
        total_secs = max(0, int(remaining.total_seconds()))
        mins, secs = divmod(total_secs, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            remaining_str = f"{hours}h {mins}m"
        elif mins:
            remaining_str = f"{mins}m {secs}s"
        else:
            remaining_str = f"{secs}s"
        lines.append(
            f"- {t.id}: en {remaining_str} "
            f"({fa.strftime('%H:%M:%S')} UTC) — \"{t.message}\""
        )

    return _ok("list_timers", "\n".join(lines))


@tool_handler("cancel_timer")
def handle_cancel_timer(ctx: ToolContext) -> ToolExecutionResult:
    timer_id = str(ctx.tool_input.get("timer_id", "")).strip()
    session_id = ctx.executor.session_id
    db_session = ctx.executor.session

    if not timer_id:
        return _err("cancel_timer", "timer_id es obligatorio.")

    task = cancel_task(db_session, session_id, timer_id)
    if task is None:
        return _err(
            "cancel_timer",
            f"No se encontró ningún temporizador pendiente con ID '{timer_id}' en esta sesión.",
        )

    return _ok("cancel_timer", f"Temporizador {timer_id} cancelado.")
