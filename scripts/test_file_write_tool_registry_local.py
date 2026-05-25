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


TRACE_ID = "trc_file_write_registry_local_test"


def expire_pending(session: Session) -> None:
    for action in session.exec(select(PendingAction).where(PendingAction.status == "pending")):
        action.status = "expired"
        session.add(action)
    session.commit()


def latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None
    return action


def main() -> None:
    init_db()

    with Session(engine) as session:
        expire_pending(session)

        executor = ToolExecutor(session)

        assert has_handler("write_file"), "write_file is not registered"

        result = dispatch_tool(
            ToolContext(
                tool_name="write_file",
                tool_input={
                    "path": "config/test-write-registry-local.txt",
                    "content": "ok registry local",
                    "create_parent_dirs": False,
                },
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert result.ok is True, result
        assert "Acción pendiente creada" in result.message, result.message

        action = latest_action(session)
        assert action.status == "pending"
        assert action.action_type == "file"
        assert action.risk_level in {"safe", "critical"}

        payload = json.loads(action.payload_json)
        assert payload["action"] == "write_file", payload
        assert payload["path"] == "config/test-write-registry-local.txt", payload
        assert payload["content"] == "ok registry local", payload
        assert payload["create_parent_dirs"] is False, payload

        blocked = dispatch_tool(
            ToolContext(
                tool_name="write_file",
                tool_input={
                    "path": "/etc/sity-registry-blocked.txt",
                    "content": "no",
                },
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert blocked.ok is False
        assert blocked.raw_result.get("local_model") == "tool-policy"

        expire_pending(session)

    print("file write tool registry local test ok")


if __name__ == "__main__":
    main()
