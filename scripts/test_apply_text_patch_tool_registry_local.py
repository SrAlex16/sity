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


TRACE_ID = "trc_apply_text_patch_registry_local_test"
TEST_PATH = "config/test-apply-text-patch-registry-local.txt"


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

    target = ROOT / TEST_PATH
    target.write_text("uno\ndos\ntres\n", encoding="utf-8")

    with Session(engine) as session:
        expire_pending(session)
        executor = ToolExecutor(session)

        assert has_handler("apply_text_patch"), "apply_text_patch is not registered"

        result = dispatch_tool(
            ToolContext(
                tool_name="apply_text_patch",
                tool_input={
                    "path": TEST_PATH,
                    "old_text": "dos",
                    "new_text": "DOS",
                },
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert result.ok is True, result
        assert "Acción pendiente creada" in result.message, result.message

        # Debe crear pending action, no modificar aún el archivo.
        assert target.read_text(encoding="utf-8") == "uno\ndos\ntres\n", "archivo modificado prematuramente"

        action = latest_action(session)
        assert action.status == "pending"
        assert action.action_type == "file"
        assert action.risk_level in {"safe", "critical"}

        payload = json.loads(action.payload_json)
        assert payload["action"] == "apply_text_patch", payload
        assert payload["path"] == TEST_PATH, payload
        assert payload["old_text"] == "dos", payload
        assert payload["new_text"] == "DOS", payload

        # diff debe estar en el raw_result
        assert "diff" in result.raw_result, result.raw_result

        # bloqueo por ruta fuera de allowlist
        blocked = dispatch_tool(
            ToolContext(
                tool_name="apply_text_patch",
                tool_input={
                    "path": "/etc/sity-registry-blocked.txt",
                    "old_text": "x",
                    "new_text": "y",
                },
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert blocked.ok is False, f"esperaba rechazo, got ok=True: {blocked}"
        assert blocked.raw_result.get("local_model") == "tool-policy", blocked.raw_result

        expire_pending(session)

    target.unlink(missing_ok=True)
    print("apply text patch tool registry local test ok")


if __name__ == "__main__":
    main()
