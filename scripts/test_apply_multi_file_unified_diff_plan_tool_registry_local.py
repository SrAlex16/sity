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


TRACE_ID = "trc_apply_multi_file_diff_registry_local_test"
TEST_A = "config/test-multi-diff-a.txt"
TEST_B = "config/test-multi-diff-b.txt"


def expire_pending(session: Session) -> None:
    for action in session.exec(select(PendingAction).where(PendingAction.status == "pending")):
        action.status = "expired"
        session.add(action)
    session.commit()


def actions_for_trace(session: Session) -> list[PendingAction]:
    return list(
        session.exec(
            select(PendingAction)
            .where(PendingAction.trace_id == TRACE_ID)
            .order_by(PendingAction.created_at.asc())
        )
    )


def main() -> None:
    init_db()

    target_a = ROOT / TEST_A
    target_b = ROOT / TEST_B
    target_a.write_text("a uno\na dos\na tres\n", encoding="utf-8")
    target_b.write_text("b uno\nb dos\nb tres\n", encoding="utf-8")

    # Un único diff unificado con dos archivos concatenados.
    combined_diff = f"""--- a/{TEST_A}
+++ b/{TEST_A}
@@ -1,3 +1,3 @@
 a uno
-a dos
+A DOS
 a tres
--- a/{TEST_B}
+++ b/{TEST_B}
@@ -1,3 +1,3 @@
 b uno
-b dos
+B DOS
 b tres
"""

    with Session(engine) as session:
        expire_pending(session)
        executor = ToolExecutor(session)

        assert has_handler("apply_multi_file_unified_diff_plan"), (
            "apply_multi_file_unified_diff_plan is not registered"
        )

        result = dispatch_tool(
            ToolContext(
                tool_name="apply_multi_file_unified_diff_plan",
                tool_input={"diff": combined_diff},
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert result.ok is True, result
        msg_lower = result.message.lower()
        assert "acción" in msg_lower or "acciones" in msg_lower, (
            f"Mensaje inesperado: {result.message}"
        )

        # No debe modificar todavía los archivos.
        assert target_a.read_text(encoding="utf-8") == "a uno\na dos\na tres\n", "archivo A modificado prematuramente"
        assert target_b.read_text(encoding="utf-8") == "b uno\nb dos\nb tres\n", "archivo B modificado prematuramente"

        actions = actions_for_trace(session)
        assert len(actions) == 2, f"Esperaba 2 acciones, got {len(actions)}"

        for action in actions:
            assert action.status == "pending", action.status
            assert action.action_type == "file", action.action_type
            payload = json.loads(action.payload_json)
            # Multi-file crea una acción apply_unified_diff por fichero.
            assert payload.get("action") == "apply_unified_diff", payload

        expire_pending(session)

        # Diff inválido rechazado.
        bad = dispatch_tool(
            ToolContext(
                tool_name="apply_multi_file_unified_diff_plan",
                tool_input={"diff": "esto no es un diff válido"},
                trace_id=TRACE_ID,
                executor=executor,
            )
        )
        assert bad.ok is False, f"esperaba rechazo de diff inválido, got ok=True: {bad}"

        expire_pending(session)

    target_a.unlink(missing_ok=True)
    target_b.unlink(missing_ok=True)
    print("apply multi file unified diff plan registry local test ok")


if __name__ == "__main__":
    main()
