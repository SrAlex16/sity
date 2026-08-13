"""
build_final_ai_response — finalization stage for the AI chat response path.

Covers, in order:
  1. Persist AIUsage row
  2. build_budget_snapshot (fresh token count after persist)
  3. write_log ai_call_completed / ai_call_failed
  4. ResponseGuard (pseudo tool call / content guard)
  5. save_chat_message (sity role)
  6. set_last_refusal if refusal_mode
  7. Return ChatMessageResponse via ai_final_response

Does NOT handle:
  - Tool loop
  - Provider calls
  - Prompts or personality
  - Early returns (local_final, sensor_*)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlmodel import Session

from app.api.schemas import ChatArtifact, ChatMessageResponse
from app.chat.budget_snapshot import build_budget_snapshot
from app.chat.response_factory import ai_final_response
from app.chat.response_guard import ResponseGuard
from app.core.refusal_tracker import set_last_refusal
from app.cortex.schemas import AIResponse
from app.memory.models import AIUsage
from app.trace.logger import write_log

_TURN_LOAD_RE = re.compile(r"<R:([+-]?\d+)>\s*\Z")


def strip_turn_load_tag(text: str) -> tuple[str, str | None]:
    """Strip trailing <R:N> tag. Returns (cleaned_text, raw_N_or_None)."""
    # Normalize Unicode MINUS SIGN U+2212 → ASCII hyphen-minus U+002D
    # Claude occasionally outputs U+2212 in negative turn-load tags.
    normalized = text.replace("−", "-")
    m = _TURN_LOAD_RE.search(normalized)
    if m:
        return _TURN_LOAD_RE.sub("", normalized).rstrip(), m.group(1)
    return text, None


def _append_pending_load(session: Session, session_id: str, load: int) -> None:
    """Atomically append a turn_load to SocialProfile.pending_loads_json.

    Uses a single INSERT...ON CONFLICT...DO UPDATE with json_insert so that
    concurrent calls for the same user_id cannot lose each other's writes.
    SQLite serializes all writes; the single statement is the critical unit.
    """
    try:
        user_id = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    now_str = datetime.now(timezone.utc).isoformat()
    session.execute(
        text(
            "INSERT INTO socialprofile (user_id, opinion, trust, pending_loads_json, created_at)"
            " VALUES (:uid, 0.0, 0.0, json_array(:load), :now)"
            " ON CONFLICT(user_id) DO UPDATE"
            " SET pending_loads_json ="
            "   json_insert(COALESCE(socialprofile.pending_loads_json, '[]'), '$[#]', :load)"
        ),
        {"uid": user_id, "load": load, "now": now_str},
    )


def build_final_ai_response(
    *,
    session: Session,
    trace_id: str,
    response: AIResponse,
    daily_budget: int,
    warning_threshold: float,
    critical_threshold: float,
    get_today_token_usage: Callable[[Session], int],
    save_message: Callable[..., None],
    refusal_mode: bool,
    user_message: str,
    updated_parameters: list[str],
    artifacts: list[ChatArtifact],
    tone_meta: str | None = None,
    output_mode: str = "text",
    source_channel: str = "web",
    session_id: str = "",
) -> ChatMessageResponse:
    # 1. Persist AIUsage row
    usage_row = AIUsage(
        trace_id=trace_id,
        session_id=None,
        provider=response.provider,
        model=response.model,
        task_type="chat_message",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        estimated_cost=0.0,
        latency_ms=response.latency_ms,
        fallback_used=response.fallback_used,
        success=response.ok,
        error_type=response.error_type,
    )
    session.add(usage_row)
    session.commit()

    # 2. Budget snapshot (after persist so daily_used is current)
    snap = build_budget_snapshot(
        daily_used=get_today_token_usage(session),
        daily_budget=daily_budget,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )

    # 3. Completion log
    write_log(
        level="INFO" if response.ok else "ERROR",
        module="cortex",
        event="ai_call_completed" if response.ok else "ai_call_failed",
        trace_id=trace_id,
        payload={
            "provider": response.provider,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_tokens": response.usage.cache_creation_tokens,
            "cache_read_tokens": response.usage.cache_read_tokens,
            "fallback_used": response.fallback_used,
            "error_type": response.error_type,
            "daily_used_tokens": snap.daily_used,
            "daily_ratio": snap.daily_ratio,
        },
    )

    # 4. ResponseGuard
    guard_result = ResponseGuard().validate_final_text(response.text)
    if not guard_result.allowed:
        write_log(
            level="WARN",
            module="chat",
            event="model_response_blocked",
            trace_id=trace_id,
            payload={"reason": guard_result.reason},
        )
    response.text = guard_result.text

    # 4.5. Strip <R:N> turn-load tag — must happen before save_message and before
    # the text reaches the user or TTS. The strip is unconditional when the tag is
    # present; storing the load value only happens for user: sessions with valid values.
    response.text, _raw_load = strip_turn_load_tag(response.text)
    if _raw_load is not None:
        try:
            _load_val = int(_raw_load)
            if not (-2 <= _load_val <= 2):
                raise ValueError(f"out of range: {_load_val}")
            if session_id.startswith("user:"):
                _append_pending_load(session, session_id, _load_val)
        except (ValueError, TypeError):
            write_log(
                level="WARN",
                module="social",
                event="turn_load_tag_invalid",
                trace_id=trace_id,
                payload={"raw_value": _raw_load, "session_id": session_id},
            )
    elif session_id.startswith("user:"):
        write_log(
            level="WARN",
            module="social",
            event="turn_load_tag_missing",
            trace_id=trace_id,
            payload={"session_id": session_id},
        )

    # 5. Persist assistant message
    # Cancelled turns still need a Sity row so the history never has two
    # consecutive user messages (which the Anthropic API rejects).
    _text_to_save = (
        "Has cancelado la operación."
        if response.error_type == "cancelled"
        else response.text
    )
    save_message(role="sity", text=_text_to_save, trace_id=trace_id,
                 tone_meta=tone_meta, output_mode=output_mode, source_channel=source_channel)

    # 6. Track refusal if applicable
    if refusal_mode:
        set_last_refusal(
            user_message=user_message,
            assistant_message=response.text,
            trace_id=trace_id,
        )

    # 6.5. Trigger background social profile update if pending_loads threshold reached.
    # save_message (step 5) already committed, so the pending load is visible to the query.
    if session_id.startswith("user:"):
        from app.social.update import maybe_trigger_social_update
        maybe_trigger_social_update(session, session_id, trace_id)

    # 7. Return response
    return ai_final_response(
        trace_id=trace_id,
        response=response,
        daily_used=snap.daily_used,
        daily_budget=snap.daily_budget,
        daily_ratio=snap.daily_ratio,
        warnings=snap.warnings,
        updated_parameters=updated_parameters,
        artifacts=artifacts,
    )
