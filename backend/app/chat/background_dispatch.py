"""Background tool dispatch — detachable tool execution and result routing.

Handles tools that run asynchronously (e.g. web_search): submits to APScheduler,
processes the result through Claude after-tools, persists to DB, and routes the
final text via the notification dispatcher (SSE + optional Web Push).
"""
from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from app.api.schemas import ChatMessageRequest
from app.chat.ai_request_builder import build_background_after_tools_ai_request
from app.chat.final_response_builder import strip_turn_load_tag
from app.chat.tool_loop_runner import ToolLoopRunOutcome
from app.core.tool_executor import ToolExecutor
from app.trace.logger import write_log


def _detach_tool(
    *,
    tool_call: "Any",
    executor: ToolExecutor,
    trace_id: str,
    runner: "Any",
    persona_prompt: str,
    user_message_with_history: str,
    prior_messages: "list[Any]",
    selected_tools: "list[Any]",
    request: ChatMessageRequest,
    ctx: "Any",
) -> ToolLoopRunOutcome:
    """Submit a detachable tool to background; return a synthetic outcome for the immediate response.

    When the job finishes:
    1. runner.run_after_tools processes the raw result so Claude generates a natural response.
    2. The response is saved to DB so the next turn has context.
    3. A proactive_message SSE event is published for the frontend to display as a new message.
    """
    from app.core.job_manager import Job, get_job_manager
    from app.core.realtime_events import publish_session_event_sync

    tool_name = tool_call.name
    tool_input = tool_call.input
    bg_trace_id = f"bg_{trace_id}"
    bg_max_tokens = max(ctx.max_tokens, ctx.ai_config.get("after_tools_min_tokens", 700))
    bg_images = [{"media_type": img.media_type, "data": img.data} for img in request.images]

    def _tool_fn() -> str:
        exec_result = executor.execute_tool_call(
            tool_name=tool_name,
            tool_input=tool_input,
            trace_id=bg_trace_id,
            client_turn_id=None,
        )
        if not exec_result.ok:
            return f"No se pudo completar la búsqueda: {exec_result.message}"
        return str(exec_result.raw_result.get("text", exec_result.message))

    def _on_done(job: Job) -> None:
        if job.status != "done":
            publish_session_event_sync(ctx.session_id, {
                "type": "proactive_message",
                "text": f"No pude completar la búsqueda: {job.error}",
                "subtype": "job_error",
                "tool_name": tool_name,
            })
            return

        raw_text = job.result_text or ""

        # Pass result through Claude so the user gets a natural-language response.
        # Uses the background-specific builder that explicitly forbids tool chaining:
        # the model must respond with what it has from this single tool result.
        try:
            after_resp = runner.run_after_tools(
                request=build_background_after_tools_ai_request(
                    trace_id=bg_trace_id,
                    persona_prompt=persona_prompt,
                    user_message=user_message_with_history,
                    max_tokens=bg_max_tokens,
                    tools=selected_tools,
                    prior_messages=prior_messages,
                    images=bg_images,
                ),
                first_response_content=[{
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_name,
                    "input": tool_input,
                }],
                tool_results=[{
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": raw_text,
                }],
            )
            if after_resp.tool_calls:
                # Model ignored the "no chaining" instruction. Use any text it produced;
                # if there is none, fall back to the raw tool result so the user gets
                # something rather than the promise of an action that will never run.
                write_log(
                    level="WARN", module="chat", event="bg_unexpected_tool_call",
                    payload={
                        "job_id": job.job_id, "tool_name": tool_name,
                        "requested_tools": [tc.name for tc in after_resp.tool_calls],
                        "after_resp_text": after_resp.text,
                    },
                )
                # after_resp.text is always a promise preamble when tool_calls is
                # present ("Voy a leer la página directamente"). Never use it as the
                # final message — it's the exact broken promise we want to avoid.
                final_text, _ = strip_turn_load_tag(
                    "No he encontrado el dato exacto en los resultados de la búsqueda."
                )
            else:
                final_text, _ = strip_turn_load_tag(after_resp.text or raw_text)
        except Exception as _bg_exc:
            write_log(level="ERROR", module="chat", event="bg_after_tools_failed",
                      payload={"job_id": job.job_id, "tool_name": tool_name,
                               "error": str(_bg_exc), "error_type": type(_bg_exc).__name__})
            final_text = raw_text

        # Persist so next turn sees this exchange in its history
        try:
            from app.memory.db import engine
            from app.memory.models import ChatMessage
            from sqlmodel import Session as _DBSession
            with _DBSession(engine) as db_sess:
                db_sess.add(ChatMessage(
                    session_id=ctx.session_id,
                    role="sity",
                    text=final_text,
                    trace_id=bg_trace_id,
                ))
                db_sess.commit()
        except Exception as _db_exc:
            write_log(level="ERROR", module="chat", event="bg_persist_failed",
                      payload={"job_id": job.job_id, "tool_name": tool_name,
                               "error": str(_db_exc), "error_type": type(_db_exc).__name__})

        # Route through dispatcher: SSE for connected subscribers + push when in background.
        # ChatMessage already committed above — dispatcher handles delivery only.
        try:
            from app.memory.db import engine as _engine
            from sqlmodel import Session as _DBSession2
            with _DBSession2(_engine) as _db:
                _dispatch_background_task_result(
                    session_id=ctx.session_id,
                    final_text=final_text,
                    bg_trace_id=bg_trace_id,
                    tool_name=tool_name,
                    job_id=job.job_id,
                    db=_db,
                )
        except Exception as _exc:
            write_log(level="WARN", module="chat", event="bg_dispatch_failed",
                      payload={"job_id": job.job_id, "tool_name": tool_name,
                               "error": str(_exc), "error_type": type(_exc).__name__})

    job_id = get_job_manager().submit(
        tool_name=tool_name,
        session_id=ctx.session_id,
        fn=_tool_fn,
        on_done=_on_done,
    )

    write_log(
        level="INFO",
        module="chat",
        event="tool_detached_to_background",
        trace_id=trace_id,
        session_id=ctx.session_id,
        payload={"tool_name": tool_name, "job_id": job_id},
    )

    return ToolLoopRunOutcome(
        early_kind=None,
        early_tool_name="",
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_results_for_claude=[{
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": json.dumps({
                "status": "en_progreso",
                "job_id": job_id,
                "message": (
                    "Búsqueda lanzada en segundo plano. "
                    "El resultado llegará como notificación en breve."
                ),
            }),
        }],
        updated_parameters=[],
        artifacts=[],
    )


def _dispatch_background_task_result(
    session_id: str,
    final_text: str,
    bg_trace_id: str,
    tool_name: str,
    job_id: str,
    db: "Session",
) -> None:
    """Route a completed background-tool result through the notification dispatcher.

    Publishes a proactive_message SSE event (with full AI response text) to any
    connected subscriber, and sends Web Push when the tab is in background or absent.
    The ChatMessage was already persisted by the caller — dispatcher handles delivery only.
    """
    from app.notifications.dispatcher import dispatch
    from app.notifications.fact import NotificationFact

    body = (
        final_text if len(final_text) <= 80
        else (final_text[:80].rsplit(" ", 1)[0] or final_text[:80])
    )
    fact = NotificationFact(
        session_id=session_id,
        notification_type="background_result",
        fact_id=f"background_result:{bg_trace_id}",
        payload={
            "title": "Sity",
            "body": body,
            "url": "/",
            "urgent": False,
            "full_text": final_text,
            "tool_name": tool_name,
            "job_id": job_id,
        },
        urgency="medium",
        subtype=tool_name,
    )
    dispatch(fact, db)
