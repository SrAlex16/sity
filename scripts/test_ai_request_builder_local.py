#!/usr/bin/env python3
"""Local tests for ai_request_builder — pure construction, no provider calls."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.chat.ai_request_builder import (  # noqa: E402
    build_after_tools_ai_request,
    build_chat_ai_request,
    build_planner_ai_request,
    max_tokens_for_verbosity,
)


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)
    ok(msg)


# ---------------------------------------------------------------------------
# max_tokens_for_verbosity
# ---------------------------------------------------------------------------

def test_verbosity_thresholds() -> None:
    print("\n==> max_tokens_for_verbosity")
    require(max_tokens_for_verbosity(0.10, 2000) == 250, "verbosity 0.10 → 250")
    require(max_tokens_for_verbosity(0.20, 2000) == 250, "verbosity 0.20 → 250")
    require(max_tokens_for_verbosity(0.21, 2000) == 450, "verbosity 0.21 → 450")
    require(max_tokens_for_verbosity(0.50, 2000) == 450, "verbosity 0.50 → 450")
    require(max_tokens_for_verbosity(0.51, 2000) == 750, "verbosity 0.51 → 750")
    require(max_tokens_for_verbosity(0.80, 2000) == 750, "verbosity 0.80 → 750")
    require(max_tokens_for_verbosity(0.81, 2000) == 1200, "verbosity 0.81 → 1200")
    require(max_tokens_for_verbosity(1.00, 2000) == 1200, "verbosity 1.00 → 1200")
    # configured_max_tokens cap
    require(max_tokens_for_verbosity(1.00, 500) == 500, "configured_max_tokens 500 caps result")
    require(max_tokens_for_verbosity(0.10, 100) == 100, "configured_max_tokens 100 caps 250")


# ---------------------------------------------------------------------------
# build_chat_ai_request
# ---------------------------------------------------------------------------

def test_chat_request() -> None:
    print("\n==> build_chat_ai_request")
    req = build_chat_ai_request(
        trace_id="trc_chat",
        persona_prompt="Eres Sity.",
        user_message="Hola.",
        max_tokens=300,
    )
    require(req.task_type == "chat_message", "task_type")
    require(req.system_prompt == "Eres Sity.", "system_prompt preserved")
    require(req.user_message == "Hola.", "user_message preserved")
    require(req.max_tokens == 300, "max_tokens preserved")
    require(req.tools_enabled is False, "tools_enabled=False")
    require(req.trace_id == "trc_chat", "trace_id preserved")


# ---------------------------------------------------------------------------
# build_planner_ai_request
# ---------------------------------------------------------------------------

def test_planner_request() -> None:
    print("\n==> build_planner_ai_request")
    fake_tools = [{"name": "read_file", "description": "lee un archivo"}]
    req = build_planner_ai_request(
        trace_id="trc_planner",
        user_message="lee README.md",
        tools=fake_tools,
    )
    require(req.task_type == "action_planner", "task_type")
    require(req.tools_enabled is True, "tools_enabled=True")
    require(req.tool_choice == {"type": "any"}, "tool_choice=any")
    require(req.tools == fake_tools, "tools list preserved")
    require(req.max_tokens == 500, "default max_tokens=500")
    require(req.trace_id == "trc_planner", "trace_id preserved")
    require("planificador" in req.system_prompt.lower(), "planner prompt present")
    require("no_action_required" in req.system_prompt, "no_action_required mentioned in prompt")


def test_planner_request_custom_max_tokens() -> None:
    print("\n==> build_planner_ai_request custom max_tokens")
    req = build_planner_ai_request(
        trace_id="trc_p2",
        user_message="test",
        tools=[],
        max_tokens=300,
    )
    require(req.max_tokens == 300, "custom max_tokens forwarded")


# ---------------------------------------------------------------------------
# build_after_tools_ai_request
# ---------------------------------------------------------------------------

def test_after_tools_request() -> None:
    print("\n==> build_after_tools_ai_request")
    base_prompt = "Eres Sity."
    req = build_after_tools_ai_request(
        trace_id="trc_after",
        persona_prompt=base_prompt,
        user_message="resultado de la herramienta aquí",
        max_tokens=700,
    )
    require(req.task_type == "chat_message_tool_result", "task_type")
    require(req.system_prompt.startswith(base_prompt), "persona_prompt is prefix of system_prompt")
    require("herramienta ya se ha ejecutado" in req.system_prompt, "after-tools suffix present")
    require("diff" in req.system_prompt, "diff instruction in suffix")
    require("confirmation_phrase" in req.system_prompt, "confirmation_phrase instruction in suffix")
    require(req.tools_enabled is False, "tools_enabled=False")
    require(req.max_tokens == 700, "max_tokens forwarded")
    require(req.tools is None, "tools=None by default")


def test_after_tools_request_with_tools() -> None:
    print("\n==> build_after_tools_ai_request with tools kwarg")
    fake_tools = [{"name": "read_file"}]
    req = build_after_tools_ai_request(
        trace_id="trc_after2",
        persona_prompt="Eres Sity.",
        user_message="test",
        max_tokens=700,
        tools=fake_tools,
    )
    require(req.tools == fake_tools, "tools list forwarded")


# ---------------------------------------------------------------------------
# Prompt idempotence — same prompt each call
# ---------------------------------------------------------------------------

def test_planner_prompt_idempotent() -> None:
    print("\n==> planner prompt is idempotent (no mutable state)")
    r1 = build_planner_ai_request(trace_id="t1", user_message="x", tools=[])
    r2 = build_planner_ai_request(trace_id="t2", user_message="x", tools=[])
    require(r1.system_prompt == r2.system_prompt, "planner prompt stable across calls")


def main() -> None:
    test_verbosity_thresholds()
    test_chat_request()
    test_planner_request()
    test_planner_request_custom_max_tokens()
    test_after_tools_request()
    test_after_tools_request_with_tools()
    test_planner_prompt_idempotent()
    print("\n[OK] All ai_request_builder tests passed")


if __name__ == "__main__":
    main()
