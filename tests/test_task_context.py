"""Tests for Eje A — task_context persistent state (docs/task-context-analysis.md).

Six cases from the validation section of the analysis document.
All use generic tool names (no Spotify references in mechanism tests).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.core.task_context import (
    _key,
    clear_task_context,
    load_task_context,
    save_task_context,
)
from app.memory.db import engine
from app.memory.models import Setting


# ---------------------------------------------------------------------------
# DB isolation — delete task_context rows before every test
# ---------------------------------------------------------------------------

_SESSION_ID = "test_session"


@pytest.fixture(autouse=True)
def _reset_task_context():
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(_SESSION_ID))).first()
        if row:
            db.delete(row)
            db.commit()


# ---------------------------------------------------------------------------
# Case 1 — Resolved data survives across subsequent turns
# ---------------------------------------------------------------------------

def test_task_context_survives_turns():
    """Data stored after turn N is available in turn N+k without re-running the tool."""
    save_task_context(_SESSION_ID, {"recurso_id": "abc123", "dispositivo_id": "xyz"})

    # Simulate turns passing without modifying the context
    result = load_task_context(_SESSION_ID)

    assert result == {"recurso_id": "abc123", "dispositivo_id": "xyz"}


# ---------------------------------------------------------------------------
# Case 2 — Explicit close clears the state
# ---------------------------------------------------------------------------

def test_task_context_explicit_close():
    """A handler returning task_context={} clears the state (task completed)."""
    save_task_context(_SESSION_ID, {"recurso_id": "abc123"})

    clear_task_context(_SESSION_ID, reason="explicit_close")

    assert load_task_context(_SESSION_ID) is None


def test_task_context_explicit_close_logs(capsys):
    """task_context_cleared event is emitted with reason=explicit_close."""
    save_task_context(_SESSION_ID, {"recurso_id": "x"})
    with patch("app.core.task_context.write_log") as mock_log:
        clear_task_context(_SESSION_ID, reason="explicit_close", trace_id="trc_test")

    mock_log.assert_called_once()
    kw = mock_log.call_args.kwargs if mock_log.call_args.kwargs else mock_log.call_args[1]
    assert kw["event"] == "task_context_cleared"
    assert kw["payload"]["reason"] == "explicit_close"


# ---------------------------------------------------------------------------
# Case 3 — TTL expiry discards the state
# ---------------------------------------------------------------------------

def test_task_context_ttl_expired():
    """State stored beyond the TTL is discarded and not injected into the planner."""
    save_task_context(_SESSION_ID, {"recurso_id": "stale_value"})

    # Backdate updated_at to beyond any realistic TTL
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(_SESSION_ID))).first()
        assert row is not None
        row.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.add(row)
        db.commit()

    # Use a 30-min TTL (default); 2 hours ago is expired
    with patch("app.core.task_context._ttl_minutes", return_value=30):
        result = load_task_context(_SESSION_ID)

    assert result is None


def test_task_context_ttl_not_yet_expired():
    """State stored within the TTL is still available."""
    save_task_context(_SESSION_ID, {"recurso_id": "fresh_value"})

    with patch("app.core.task_context._ttl_minutes", return_value=30):
        result = load_task_context(_SESSION_ID)

    assert result == {"recurso_id": "fresh_value"}


def test_task_context_ttl_expired_logs():
    """task_context_cleared is emitted with reason=ttl_expired when TTL fires."""
    save_task_context(_SESSION_ID, {"recurso_id": "x"})

    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(_SESSION_ID))).first()
        row.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.add(row)
        db.commit()

    with patch("app.core.task_context._ttl_minutes", return_value=30), \
         patch("app.core.task_context.write_log") as mock_log:
        load_task_context(_SESSION_ID)

    calls = [c for c in mock_log.call_args_list
             if c.kwargs.get("event") == "task_context_cleared"]
    assert calls, "Expected task_context_cleared event"
    assert calls[0].kwargs["payload"]["reason"] == "ttl_expired"


# ---------------------------------------------------------------------------
# Case 4 — Planner message includes the task_context block
# ---------------------------------------------------------------------------

def test_planner_message_includes_task_context_block():
    """PromptContextBuilder injects the task_context block into planner_user_message."""
    from unittest.mock import MagicMock
    from app.chat.prompt_context import PromptContextBuilder

    builder = PromptContextBuilder(get_recent_messages=lambda s, limit: [])
    ctx = builder.build(
        session=None,
        message="pon la playlist",
        history_limit=4,
        planner_history_limit=4,
        task_context={"recurso_uri": "spotify:playlist:abc", "dispositivo_id": "dev1"},
    )

    assert "Contexto de tarea activa" in ctx.planner_user_message
    assert "recurso_uri: spotify:playlist:abc" in ctx.planner_user_message
    assert "dispositivo_id: dev1" in ctx.planner_user_message
    assert "pon la playlist" in ctx.planner_user_message


def test_planner_message_no_block_when_context_empty():
    """No task_context block injected when there is no active context."""
    from app.chat.prompt_context import PromptContextBuilder

    builder = PromptContextBuilder(get_recent_messages=lambda s, limit: [])
    ctx = builder.build(
        session=None,
        message="hola",
        history_limit=4,
        planner_history_limit=4,
        task_context=None,
    )

    assert "Contexto de tarea activa" not in ctx.planner_user_message


# ---------------------------------------------------------------------------
# Case 5 — Multiple handlers in the same turn are merged
# ---------------------------------------------------------------------------

def test_task_context_merge_multiple_handlers():
    """Two save_task_context calls (from different handlers) merge, not overwrite."""
    save_task_context(_SESSION_ID, {"recurso_uri": "uri_from_tool_A"})
    save_task_context(_SESSION_ID, {"dispositivo_id": "id_from_tool_B"})

    result = load_task_context(_SESSION_ID)

    assert result == {
        "recurso_uri": "uri_from_tool_A",
        "dispositivo_id": "id_from_tool_B",
    }


def test_task_context_merge_preserves_untouched_keys():
    """Saving new keys does not remove existing unrelated keys."""
    save_task_context(_SESSION_ID, {"recurso_uri": "original", "other_key": "keep_me"})
    save_task_context(_SESSION_ID, {"recurso_uri": "updated"})

    result = load_task_context(_SESSION_ID)

    assert result["other_key"] == "keep_me"
    assert result["recurso_uri"] == "updated"


# ---------------------------------------------------------------------------
# Case 6 — Updated value replaces stale value correctly
# ---------------------------------------------------------------------------

def test_task_context_update_replaces_stale_value():
    """When a handler re-resolves a key, the new value replaces the old one."""
    save_task_context(_SESSION_ID, {"dispositivo_id": "old_device_X"})
    save_task_context(_SESSION_ID, {"dispositivo_id": "new_device_Y"})

    result = load_task_context(_SESSION_ID)

    assert result == {"dispositivo_id": "new_device_Y"}


def test_task_context_update_logs_keys_not_values():
    """task_context_updated log contains key names but NOT values."""
    with patch("app.core.task_context.write_log") as mock_log:
        save_task_context(
            _SESSION_ID,
            {"recurso_uri": "SECRET_URI", "dispositivo_id": "SECRET_ID"},
            trace_id="trc_abc",
        )

    update_calls = [c for c in mock_log.call_args_list
                    if c.kwargs.get("event") == "task_context_updated"]
    assert update_calls, "Expected task_context_updated event"
    payload = update_calls[0].kwargs["payload"]
    assert set(payload["keys"]) == {"recurso_uri", "dispositivo_id"}
    # Values must NOT appear in the log payload
    assert "SECRET_URI" not in str(payload)
    assert "SECRET_ID" not in str(payload)
