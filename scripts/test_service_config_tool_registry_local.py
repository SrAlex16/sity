#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlmodel import Session, select  # noqa: E402

from app.core.tool_executor import ToolExecutor  # noqa: E402
from app.memory.db import engine, init_db  # noqa: E402
from app.memory.models import PendingAction  # noqa: E402
from app.tools.registry import ToolContext, dispatch_tool, has_handler  # noqa: E402

TRACE_ID = "trc_service_config_registry_local_test"


def latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None, "No pending action found for test trace_id"
    return action


def expire_test_actions(session: Session) -> None:
    for action in session.exec(
        select(PendingAction).where(PendingAction.trace_id == TRACE_ID)
    ):
        action.status = "expired"
        session.add(action)
    session.commit()


def main() -> None:
    init_db()

    with Session(engine) as session:
        expire_test_actions(session)
        executor = ToolExecutor(session)

        # ── Registration ──────────────────────────────────────────────────────
        for tool_name in ["add_allowed_service", "remove_allowed_service"]:
            assert has_handler(tool_name), f"{tool_name} not registered"
        print("[OK] both handlers registered")

        # ── Happy path: add and remove ────────────────────────────────────────
        for tool_name in ["add_allowed_service", "remove_allowed_service"]:
            result = dispatch_tool(ToolContext(
                tool_name=tool_name,
                tool_input={"service_name": "sity-test"},
                trace_id=TRACE_ID,
                executor=executor,
            ))

            assert result.ok is True, f"{tool_name}: {result}"
            assert "Acción pendiente creada" in result.message, result.message

            action = latest_action(session)
            assert action.status == "pending", f"Expected pending, got {action.status}"
            assert action.action_type == "system_config"
            assert action.risk_level == "critical"

            payload = json.loads(action.payload_json)
            assert payload == {"action": tool_name, "service_name": "sity-test"}, payload

            action.status = "expired"
            session.add(action)
            session.commit()
            print(f"[OK] {tool_name} creates pending action with correct payload")

        # ── Invalid service name: rejected immediately ─────────────────────────
        for bad_name in ["../../bad", "bad service", "", "bad/path"]:
            bad = dispatch_tool(ToolContext(
                tool_name="add_allowed_service",
                tool_input={"service_name": bad_name},
                trace_id=TRACE_ID,
                executor=executor,
            ))
            assert bad.ok is False, f"Expected rejection for {bad_name!r}, got ok=True"
            assert bad.raw_result.get("local_model") == "tool-policy", bad.raw_result
        print("[OK] invalid service names rejected with tool-policy")

        # ── Valid edge-case names ─────────────────────────────────────────────
        for valid_name in ["sity-backend", "my.service", "service_v2", "svc@host"]:
            ok_result = dispatch_tool(ToolContext(
                tool_name="add_allowed_service",
                tool_input={"service_name": valid_name},
                trace_id=TRACE_ID,
                executor=executor,
            ))
            assert ok_result.ok is True, f"Expected ok for {valid_name!r}: {ok_result}"
        expire_test_actions(session)
        print("[OK] valid edge-case service names accepted")

    print("\nservice config tool registry local test ok")


if __name__ == "__main__":
    main()
