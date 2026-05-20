#!/home/alex/projects/sity/backend/.venv/bin/python3
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))


from app.actions.confirmation_manager import ConfirmationManager  # noqa: E402
from app.memory.models import ChatMessage, PendingAction, utc_now  # noqa: E402


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    ok(message)


def create_test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def add_sity_message(session: Session, text: str) -> None:
    session.add(
        ChatMessage(
            session_id="default",
            role="sity",
            text=text,
            trace_id="local_confirmation_test",
        )
    )
    session.commit()


def get_action(session: Session, action_id: str) -> PendingAction:
    action = session.exec(
        select(PendingAction).where(PendingAction.id == action_id)
    ).first()

    if not action:
        fail(f"Action not found: {action_id}")

    return action


def main() -> None:
    session = create_test_session()
    manager = ConfirmationManager(session)

    print("==> exact confirmation")

    created = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Test exact confirmation",
        payload={"action": "write_file", "path": "config/test.txt", "content": "hola"},
        trace_id="trc_local_exact",
    )

    found = manager.find_pending_action_by_confirmation(created.confirmation_phrase)
    require(found is not None, "exact confirmation finds action")
    require(found.id == created.id, "exact confirmation returns correct action")

    found_upper = manager.find_pending_action_by_confirmation(
        created.confirmation_phrase.upper()
    )
    require(found_upper is not None, "exact confirmation is case-insensitive")
    require(found_upper.id == created.id, "case-insensitive exact confirmation returns correct action")

    print("==> action id extraction")

    extracted = manager.extract_action_id_from_message(
        f"por favor confirmo ejecutar {created.id}"
    )
    require(extracted == created.id, "extract_action_id_from_message extracts action id")

    extracted_none = manager.extract_action_id_from_message("confirmo ejecutar act_NOPE")
    require(extracted_none is None, "invalid action id format is ignored")

    print("==> equivalent pending action")

    equivalent = manager.find_equivalent_pending_action(
        action_type="file",
        payload={"action": "write_file", "path": "config/test.txt", "content": "hola"},
    )
    require(equivalent is not None, "find_equivalent_pending_action finds matching payload")
    require(equivalent.id == created.id, "equivalent pending action id matches")

    not_equivalent = manager.find_equivalent_pending_action(
        action_type="file",
        payload={"action": "write_file", "path": "config/other.txt", "content": "hola"},
    )
    require(not_equivalent is None, "find_equivalent_pending_action ignores different payload")

    print("==> generic confirmation helpers")

    require(manager.is_generic_confirmation_message("sí, hazlo"), "sí, hazlo is generic confirmation")
    require(manager.is_generic_confirmation_message("vale"), "vale is generic confirmation")
    require(not manager.is_generic_confirmation_message("sí, de tu propio repo"), "sí, de tu propio repo is not clear generic confirmation")
    require(not manager.is_generic_confirmation_message("lee el README"), "normal request is not generic confirmation")

    print("==> context confirmation requires last Sity message reference")

    contextual = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Test contextual confirmation",
        payload={"action": "write_file", "path": "config/context.txt", "content": "hola"},
        trace_id="trc_local_context",
    )

    no_context = manager.find_pending_action_by_context("sí, hazlo")
    require(no_context is None or no_context.id != contextual.id, "context confirmation does not match without last Sity reference")

    add_sity_message(
        session,
        f"Acción pendiente creada. Confirma con: `{contextual.confirmation_phrase}`",
    )

    with_context = manager.find_pending_action_by_context("sí, hazlo")
    require(with_context is not None, "context confirmation matches with last Sity reference")
    require(with_context.id == contextual.id, "context confirmation returns referenced action")

    vague_followup = manager.find_pending_action_by_context("sí, de tu propio repo")
    require(vague_followup is None, "vague follow-up does not confirm contextual action")

    print("==> executed action is not active")

    action = get_action(session, contextual.id)
    manager.mark_executed(action, "trc_local_executed")

    found_after_executed = manager.find_pending_action_by_confirmation(
        contextual.confirmation_phrase
    )
    require(found_after_executed is None, "executed action is not found as pending")

    action_by_id = manager.find_action_by_id(contextual.id)
    require(action_by_id is not None, "executed action can still be found by id")
    require(action_by_id.status == "executed", "executed action status is executed")

    print("==> expired action is not active")

    expired = PendingAction(
        id="act_deadbeef",
        action_type="file",
        risk_level="critical",
        status="pending",
        summary="Expired test action",
        payload_json=json.dumps({"action": "write_file", "path": "config/expired.txt"}),
        confirmation_phrase="confirmo ejecutar act_deadbeef",
        created_at=utc_now() - timedelta(minutes=30),
        expires_at=utc_now() - timedelta(minutes=15),
        trace_id="trc_local_expired",
    )
    session.add(expired)
    session.commit()

    found_expired = manager.find_pending_action_by_confirmation(
        "confirmo ejecutar act_deadbeef"
    )
    require(found_expired is None, "expired action is not returned as pending")

    expired_after = manager.find_action_by_id("act_deadbeef")
    require(expired_after is not None, "expired action can still be found by id")
    require(expired_after.status == "expired", "expired action status is marked expired")

    print("==> multiple pending actions")

    multi_a = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Multi A",
        payload={"action": "write_file", "path": "config/multi-a.txt", "content": "a"},
        trace_id="trc_local_multi_a",
    )
    multi_b = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Multi B",
        payload={"action": "write_file", "path": "config/multi-b.txt", "content": "b"},
        trace_id="trc_local_multi_b",
    )

    require(manager.has_multiple_active_pending_actions(), "multiple active pending actions detected")

    exact_multi_a = manager.find_pending_action_by_confirmation(
        multi_a.confirmation_phrase
    )
    require(exact_multi_a is not None, "exact confirmation still works with multiple pending actions")
    require(exact_multi_a.id == multi_a.id, "exact confirmation chooses requested action with multiple pending actions")

    exact_multi_b = manager.find_pending_action_by_confirmation(
        multi_b.confirmation_phrase
    )
    require(exact_multi_b is not None, "second exact confirmation works with multiple pending actions")
    require(exact_multi_b.id == multi_b.id, "second exact confirmation chooses requested action")

    print("==> route-level invariant reminder")

    require(
        manager.has_multiple_active_pending_actions()
        and manager.is_generic_confirmation_message("sí, hazlo"),
        "routes_chat must reject generic confirmation before context when multiple actions are pending",
    )

    ok("All confirmation manager local tests passed")


if __name__ == "__main__":
    main()
