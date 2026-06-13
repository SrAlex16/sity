from __future__ import annotations

import pytest

from app.chat.ai_request_builder import (
    build_after_tools_ai_request,
    build_chat_ai_request,
    build_planner_ai_request,
    max_tokens_for_verbosity,
)


# ---------------------------------------------------------------------------
# max_tokens_for_verbosity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verbosity,max_cfg,expected", [
    (0.10, 2000, 250),
    (0.20, 2000, 250),
    (0.21, 2000, 450),
    (0.50, 2000, 450),
    (0.51, 2000, 750),
    (0.80, 2000, 750),
    (0.81, 2000, 1200),
    (1.00, 2000, 1200),
    (1.00, 500,  500),   # configured_max_tokens cap
    (0.10, 100,  100),   # configured_max_tokens cap below verbosity minimum
])
def test_max_tokens_for_verbosity(verbosity: float, max_cfg: int, expected: int) -> None:
    assert max_tokens_for_verbosity(verbosity, max_cfg) == expected


# ---------------------------------------------------------------------------
# build_chat_ai_request
# ---------------------------------------------------------------------------

def test_chat_request_task_type() -> None:
    req = build_chat_ai_request(
        trace_id="trc_chat", persona_prompt="Eres Sity.",
        user_message="Hola.", max_tokens=300,
    )
    assert req.task_type == "chat_message"


def test_chat_request_fields_preserved() -> None:
    req = build_chat_ai_request(
        trace_id="trc_chat", persona_prompt="Eres Sity.",
        user_message="Hola.", max_tokens=300,
    )
    assert req.system_prompt == "Eres Sity."
    assert req.user_message == "Hola."
    assert req.max_tokens == 300
    assert req.tools_enabled is False
    assert req.trace_id == "trc_chat"


# ---------------------------------------------------------------------------
# build_planner_ai_request
# ---------------------------------------------------------------------------

def test_planner_request_task_type() -> None:
    req = build_planner_ai_request(trace_id="t", user_message="x", tools=[])
    assert req.task_type == "action_planner"


def test_planner_request_tools_enabled() -> None:
    fake_tools = [{"name": "read_file", "description": "lee un archivo"}]
    req = build_planner_ai_request(
        trace_id="trc_planner", user_message="lee README.md", tools=fake_tools,
    )
    assert req.tools_enabled is True
    assert req.tool_choice == {"type": "any"}
    assert req.tools == fake_tools
    assert req.max_tokens == 500
    assert req.trace_id == "trc_planner"


def test_planner_request_prompt_content() -> None:
    req = build_planner_ai_request(trace_id="t", user_message="x", tools=[])
    assert "planificador" in req.system_prompt.lower()
    assert "no_action_required" in req.system_prompt


def test_planner_request_custom_max_tokens() -> None:
    req = build_planner_ai_request(trace_id="t", user_message="x", tools=[], max_tokens=300)
    assert req.max_tokens == 300


def test_planner_prompt_idempotent() -> None:
    r1 = build_planner_ai_request(trace_id="t1", user_message="x", tools=[])
    r2 = build_planner_ai_request(trace_id="t2", user_message="x", tools=[])
    assert r1.system_prompt == r2.system_prompt


# ---------------------------------------------------------------------------
# build_after_tools_ai_request
# ---------------------------------------------------------------------------

def test_after_tools_request_task_type() -> None:
    req = build_after_tools_ai_request(
        trace_id="t", persona_prompt="Eres Sity.", user_message="x", max_tokens=700,
    )
    assert req.task_type == "chat_message_tool_result"


def test_after_tools_request_prompt_structure() -> None:
    base = "Eres Sity."
    req = build_after_tools_ai_request(
        trace_id="t", persona_prompt=base, user_message="x", max_tokens=700,
    )
    assert req.system_prompt.startswith(base)
    assert "herramienta ya se ha ejecutado" in req.system_prompt
    assert "diff" in req.system_prompt
    assert "confirmation_phrase" in req.system_prompt


def test_after_tools_request_no_tools_by_default() -> None:
    req = build_after_tools_ai_request(
        trace_id="t", persona_prompt="Eres Sity.", user_message="x", max_tokens=700,
    )
    assert req.tools_enabled is False
    assert req.tools is None


def test_after_tools_request_with_tools_kwarg() -> None:
    fake_tools = [{"name": "read_file"}]
    req = build_after_tools_ai_request(
        trace_id="t", persona_prompt="Eres Sity.", user_message="x",
        max_tokens=700, tools=fake_tools,
    )
    assert req.tools == fake_tools


def test_after_tools_prompt_contains_memory_rules() -> None:
    req = build_after_tools_ai_request(
        trace_id="t", persona_prompt="Eres Sity.", user_message="x", max_tokens=700,
    )
    assert "search_conversation_history" in req.system_prompt
    assert "evidencia interna" in req.system_prompt
    assert "no narres" in req.system_prompt.lower() or "no narr" in req.system_prompt.lower()
    assert "fragmento" in req.system_prompt
