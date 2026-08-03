"""Tests for app.tools.handlers.memory_tools.

Covers all formatting helpers (_fmt_ts, _fmt_ctx, _fmt_fragment,
_fmt_recall_result) and the tool handler handle_search_conversation_history
(empty-query error path + successful recall path).

Mocking strategy: MemoryRecallRunner.recall is patched so no DB is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

from app.memory.recall import MemoryFragment, MemoryRecallResult
from app.memory.search import MessageContext
from app.tools.handlers.memory_tools import (
    _fmt_ctx,
    _fmt_fragment,
    _fmt_recall_result,
    _fmt_ts,
    handle_search_conversation_history,
)
from app.tools.registry import ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DT = datetime(2024, 3, 15, 10, 30, tzinfo=timezone.utc)


def _ctx_obj(role="user", text="hello", dt=_DT) -> MessageContext:
    return MessageContext(role=role, text=text, created_at=dt)


def _fragment(
    *,
    message_id: int | None = 42,
    role: str = "user",
    text: str = "hola",
    prev: MessageContext | None = None,
    next_: MessageContext | None = None,
) -> MemoryFragment:
    return MemoryFragment(
        message_id=message_id,
        timestamp=_DT,
        role=role,
        text=text,
        prev=prev,
        next=next_,
    )


def _recall_result(
    *,
    status: str = "found",
    queries: list[str] | None = None,
    fragments: list[MemoryFragment] | None = None,
    summary: str = "Encontrado.",
    confidence: float = 0.9,
    truncated: bool = False,
    windows_read: int = 0,
    anchor_ids: list[int] | None = None,
) -> MemoryRecallResult:
    return MemoryRecallResult(
        status=status,
        queries_tried=queries or ["hola"],
        fragments=fragments or [],
        evidence_summary=summary,
        result_confidence=confidence,
        truncated=truncated,
        windows_read=windows_read,
        anchor_message_ids=anchor_ids or [],
    )


def _tool_ctx(query: str = "hola") -> ToolContext:
    executor = MagicMock()
    executor.session_id = "sess_test"
    return ToolContext(
        tool_name="search_conversation_history",
        tool_input={"query": query},
        trace_id="trc_test",
        executor=executor,
    )


# ---------------------------------------------------------------------------
# _fmt_ts
# ---------------------------------------------------------------------------

class TestFmtTs:
    def test_formats_datetime(self):
        assert _fmt_ts(_DT) == "2024-03-15 10:30"

    def test_none_returns_empty_string(self):
        assert _fmt_ts(None) == ""

    def test_invalid_object_returns_str(self):
        class Bad:
            def strftime(self, _):
                raise AttributeError("no strftime")
            def __str__(self):
                return "bad-dt"
        assert _fmt_ts(Bad()) == "bad-dt"


# ---------------------------------------------------------------------------
# _fmt_ctx
# ---------------------------------------------------------------------------

class TestFmtCtx:
    def test_user_role_label(self):
        result = _fmt_ctx("anterior", _ctx_obj(role="user", text="hi"))
        assert "Usuario" in result
        assert "hi" in result
        assert "[anterior]" in result

    def test_sity_role_label(self):
        result = _fmt_ctx("siguiente", _ctx_obj(role="sity", text="resp"))
        assert "Sity" in result

    def test_unknown_role_used_as_is(self):
        result = _fmt_ctx("X", _ctx_obj(role="admin", text="t"))
        assert "admin" in result

    def test_timestamp_included(self):
        result = _fmt_ctx("A", _ctx_obj(dt=_DT))
        assert "2024-03-15" in result


# ---------------------------------------------------------------------------
# _fmt_fragment
# ---------------------------------------------------------------------------

class TestFmtFragment:
    def test_basic_fragment_no_context(self):
        f = _fragment(message_id=7, role="user", text="test msg")
        result = _fmt_fragment(1, f)
        assert "Fragmento 1" in result
        assert "msg #7" in result
        assert "Usuario" in result
        assert "test msg" in result

    def test_none_message_id_shows_msg(self):
        f = _fragment(message_id=None, text="x")
        result = _fmt_fragment(1, f)
        assert "msg #" not in result
        assert "[msg," in result or "msg," in result

    def test_prev_context_included(self):
        prev = _ctx_obj(role="user", text="pregunta previa")
        f = _fragment(prev=prev)
        result = _fmt_fragment(1, f)
        assert "[anterior]" in result
        assert "pregunta previa" in result

    def test_next_context_included(self):
        nxt = _ctx_obj(role="sity", text="respuesta siguiente")
        f = _fragment(next_=nxt)
        result = _fmt_fragment(1, f)
        assert "[siguiente]" in result
        assert "respuesta siguiente" in result

    def test_sity_role_in_fragment(self):
        f = _fragment(role="sity", text="respuesta sity")
        result = _fmt_fragment(2, f)
        assert "Sity" in result


# ---------------------------------------------------------------------------
# _fmt_recall_result
# ---------------------------------------------------------------------------

class TestFmtRecallResult:
    def test_found_status_with_fragments(self):
        f = _fragment(text="dato recordado")
        r = _recall_result(status="found", fragments=[f], confidence=0.85)
        result = _fmt_recall_result(r)
        assert "found" in result
        assert "0.85" in result
        assert "dato recordado" in result
        assert "Evidencia:" in result

    def test_not_found_shows_sin_resultados(self):
        r = _recall_result(status="not_found", fragments=[])
        result = _fmt_recall_result(r)
        assert "Sin resultados." in result

    def test_queries_listed(self):
        r = _recall_result(queries=["q1", "q2"])
        result = _fmt_recall_result(r)
        assert '"q1"' in result
        assert '"q2"' in result

    def test_truncated_flag_shown(self):
        r = _recall_result(truncated=True)
        result = _fmt_recall_result(r)
        assert "truncados" in result

    def test_no_truncated_message_when_false(self):
        r = _recall_result(truncated=False)
        result = _fmt_recall_result(r)
        assert "truncados" not in result

    def test_windows_read_shown_when_nonzero(self):
        r = _recall_result(windows_read=3, anchor_ids=[10, 20])
        result = _fmt_recall_result(r)
        assert "Ventanas de contexto leídas: 3" in result
        assert "#10" in result
        assert "#20" in result

    def test_windows_read_hidden_when_zero(self):
        r = _recall_result(windows_read=0)
        result = _fmt_recall_result(r)
        assert "Ventanas" not in result

    def test_evidence_summary_included(self):
        r = _recall_result(summary="El usuario mencionó X.")
        result = _fmt_recall_result(r)
        assert "El usuario mencionó X." in result

    def test_multiple_fragments_numbered(self):
        frags = [_fragment(text=f"frag {i}") for i in range(3)]
        r = _recall_result(fragments=frags)
        result = _fmt_recall_result(r)
        assert "Fragmento 1" in result
        assert "Fragmento 2" in result
        assert "Fragmento 3" in result


# ---------------------------------------------------------------------------
# handle_search_conversation_history
# ---------------------------------------------------------------------------

class TestHandleSearchConversationHistory:
    def test_empty_query_returns_error(self):
        ctx = _tool_ctx(query="")
        result = handle_search_conversation_history(ctx)
        assert result.ok is False
        assert result.raw_result["success"] is False

    def test_whitespace_only_query_returns_error(self):
        ctx = _tool_ctx(query="   ")
        result = handle_search_conversation_history(ctx)
        assert result.ok is False

    def test_missing_query_key_returns_error(self):
        executor = MagicMock()
        executor.session_id = "s"
        ctx = ToolContext(
            tool_name="search_conversation_history",
            tool_input={},
            trace_id="trc",
            executor=executor,
        )
        result = handle_search_conversation_history(ctx)
        assert result.ok is False

    def test_valid_query_calls_recall(self):
        recall_result = _recall_result(
            status="found",
            fragments=[_fragment(text="recuerdo")],
            confidence=0.75,
        )
        with patch("app.tools.handlers.memory_tools.MemoryRecallRunner") as MockRunner:
            MockRunner.return_value.recall.return_value = recall_result
            ctx = _tool_ctx(query="algo que dije")
            result = handle_search_conversation_history(ctx)

        assert result.ok is True
        assert result.raw_result["success"] is True
        assert result.raw_result["status"] == "found"
        assert result.raw_result["count"] == 1
        assert "recuerdo" in result.raw_result["text"]

    def test_recall_called_with_session_id(self):
        recall_result = _recall_result()
        with patch("app.tools.handlers.memory_tools.MemoryRecallRunner") as MockRunner:
            MockRunner.return_value.recall.return_value = recall_result
            ctx = _tool_ctx(query="test")
            handle_search_conversation_history(ctx)

        call_kwargs = MockRunner.return_value.recall.call_args.kwargs
        assert call_kwargs["session_id"] == "sess_test"
        assert call_kwargs["query"] == "test"

    def test_not_found_still_returns_ok_true(self):
        recall_result = _recall_result(status="not_found", fragments=[])
        with patch("app.tools.handlers.memory_tools.MemoryRecallRunner") as MockRunner:
            MockRunner.return_value.recall.return_value = recall_result
            result = handle_search_conversation_history(_tool_ctx(query="algo"))

        assert result.ok is True
        assert result.raw_result["count"] == 0
