#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlmodel import Session, select  # noqa: E402

from app.actions.file_actions import execute_file_action  # noqa: E402
from app.core.tool_executor import ToolExecutor  # noqa: E402
from app.memory.db import engine, init_db  # noqa: E402
from app.memory.models import PendingAction  # noqa: E402
from app.tools.registry import ToolContext, dispatch_tool, has_handler  # noqa: E402


TRACE_ID = "trc_rollback_registry_local_test"
TEST_PATH = "config/test-rollback-registry-local.txt"


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


def make_reversible_change() -> str:
    """Write a real file via file_actions so audit+backup are created. Returns backup_path."""
    target = ROOT / TEST_PATH
    target.write_text("contenido original\n", encoding="utf-8")

    result = execute_file_action({
        "action": "write_file",
        "path": TEST_PATH,
        "content": "contenido modificado\n",
        "trace_id": TRACE_ID,
    })
    assert result.get("ok"), f"write_file para generar backup falló: {result}"
    backup = result.get("backup") or {}
    backup_path = backup.get("backup_path", "")
    assert backup_path, f"write_file no generó backup_path: {result}"
    return backup_path


def main() -> None:
    init_db()

    # ── Registration ──────────────────────────────────────────────────────────
    for tool_name in ["rollback_latest_file_change", "rollback_file_change"]:
        assert has_handler(tool_name), f"{tool_name} is not registered"
    print("[OK] both rollback handlers registered")

    # ── Setup: generate a real reversible change ──────────────────────────────
    backup_path = make_reversible_change()
    target = ROOT / TEST_PATH
    assert target.read_text(encoding="utf-8") == "contenido modificado\n", "setup write falló"
    print(f"[OK] reversible change created, backup_path={backup_path!r}")

    with Session(engine) as session:
        expire_pending(session)
        executor = ToolExecutor(session)

        # ── rollback_latest_file_change: happy path ───────────────────────────
        result = dispatch_tool(
            ToolContext(
                tool_name="rollback_latest_file_change",
                tool_input={"include_rollbacks": False},
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert result.ok is True, f"rollback_latest_file_change falló: {result}"
        assert "Acción pendiente creada" in result.message, result.message

        # El archivo NO debe haber cambiado todavía.
        assert target.read_text(encoding="utf-8") == "contenido modificado\n", (
            "rollback_latest_file_change modificó el archivo antes de confirmación"
        )

        action = latest_action(session)
        assert action.status == "pending"
        assert action.action_type == "file"
        assert action.risk_level == "critical"

        payload = json.loads(action.payload_json)
        assert payload["action"] == "rollback_file_change", payload
        assert "backup_path" in payload, payload
        retrieved_backup_path = payload["backup_path"]

        expire_pending(session)
        print("[OK] rollback_latest_file_change creates pending action, file unchanged")

        # ── rollback_file_change: happy path con backup_path concreto ─────────
        result2 = dispatch_tool(
            ToolContext(
                tool_name="rollback_file_change",
                tool_input={"backup_path": retrieved_backup_path},
                trace_id=TRACE_ID,
                executor=executor,
            )
        )

        assert result2.ok is True, f"rollback_file_change falló: {result2}"
        assert "Acción pendiente creada" in result2.message, result2.message

        # El archivo sigue sin cambiar.
        assert target.read_text(encoding="utf-8") == "contenido modificado\n", (
            "rollback_file_change modificó el archivo antes de confirmación"
        )

        action2 = latest_action(session)
        assert action2.status == "pending"
        assert action2.action_type == "file"

        payload2 = json.loads(action2.payload_json)
        assert payload2["action"] == "rollback_file_change", payload2
        assert payload2["backup_path"] == retrieved_backup_path, payload2

        expire_pending(session)
        print("[OK] rollback_file_change creates pending action, file unchanged")

        # ── rollback_file_change: backup_path inválido rechazado ──────────────
        bad = dispatch_tool(
            ToolContext(
                tool_name="rollback_file_change",
                tool_input={"backup_path": "backups/no-existe-nunca.bak"},
                trace_id=TRACE_ID,
                executor=executor,
            )
        )
        assert bad.ok is False, f"esperaba rechazo de backup inválido, got ok=True: {bad}"
        expire_pending(session)
        print("[OK] rollback_file_change rejects unknown backup_path")

    target.unlink(missing_ok=True)
    print("\nrollback tools registry local test ok")


if __name__ == "__main__":
    main()
