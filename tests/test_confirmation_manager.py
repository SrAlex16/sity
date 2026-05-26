from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.actions.confirmation_manager import ConfirmationManager
from app.memory.models import ChatMessage, PendingAction, utc_now


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add_sity_message(session: Session, text: str) -> None:
    session.add(
        ChatMessage(
            session_id="default",
            role="sity",
            text=text,
            trace_id="local_confirmation_test",
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# 1. Exact confirmation + action_id extraction + equivalent lookup
# ---------------------------------------------------------------------------

def test_exact_confirmation_and_related_lookups() -> None:
    session = _make_session()
    manager = ConfirmationManager(session)

    created = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Test exact confirmation",
        payload={"action": "write_file", "path": "config/test.txt", "content": "hola"},
        trace_id="trc_local_exact",
    )

    # exact confirmation
    found = manager.find_pending_action_by_confirmation(created.confirmation_phrase)
    assert found is not None
    assert found.id == created.id

    # case-insensitive
    found_upper = manager.find_pending_action_by_confirmation(
        created.confirmation_phrase.upper()
    )
    assert found_upper is not None
    assert found_upper.id == created.id

    # action_id extraction
    extracted = manager.extract_action_id_from_message(
        f"por favor confirmo ejecutar {created.id}"
    )
    assert extracted == created.id

    extracted_none = manager.extract_action_id_from_message("confirmo ejecutar act_NOPE")
    assert extracted_none is None

    # equivalent pending action
    equivalent = manager.find_equivalent_pending_action(
        action_type="file",
        payload={"action": "write_file", "path": "config/test.txt", "content": "hola"},
    )
    assert equivalent is not None
    assert equivalent.id == created.id

    not_equivalent = manager.find_equivalent_pending_action(
        action_type="file",
        payload={"action": "write_file", "path": "config/other.txt", "content": "hola"},
    )
    assert not_equivalent is None


# ---------------------------------------------------------------------------
# 2. Generic confirmation helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", ["sí, hazlo", "vale"])
def test_generic_confirmation_positive(msg: str) -> None:
    session = _make_session()
    manager = ConfirmationManager(session)
    assert manager.is_generic_confirmation_message(msg)


@pytest.mark.parametrize("msg", [
    "sí, de tu propio repo",
    "lee el README",
])
def test_generic_confirmation_negative(msg: str) -> None:
    session = _make_session()
    manager = ConfirmationManager(session)
    assert not manager.is_generic_confirmation_message(msg)


# ---------------------------------------------------------------------------
# 3. Context confirmation requires last Sity message reference
# ---------------------------------------------------------------------------

def test_context_confirmation_and_executed_status() -> None:
    session = _make_session()
    manager = ConfirmationManager(session)

    contextual = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary="Test contextual confirmation",
        payload={"action": "write_file", "path": "config/context.txt", "content": "hola"},
        trace_id="trc_local_context",
    )

    # without Sity message referencing this action, context confirmation must not match
    no_context = manager.find_pending_action_by_context("sí, hazlo")
    assert no_context is None or no_context.id != contextual.id

    _add_sity_message(
        session,
        f"Acción pendiente creada. Confirma con: `{contextual.confirmation_phrase}`",
    )

    with_context = manager.find_pending_action_by_context("sí, hazlo")
    assert with_context is not None
    assert with_context.id == contextual.id

    # vague follow-up must NOT confirm
    vague = manager.find_pending_action_by_context("sí, de tu propio repo")
    assert vague is None

    # mark executed → action must disappear from pending lookup
    action = session.exec(
        select(PendingAction).where(PendingAction.id == contextual.id)
    ).first()
    assert action is not None
    manager.mark_executed(action, "trc_local_executed")

    assert manager.find_pending_action_by_confirmation(contextual.confirmation_phrase) is None

    by_id = manager.find_action_by_id(contextual.id)
    assert by_id is not None
    assert by_id.status == "executed"


# ---------------------------------------------------------------------------
# 4. Expired action
# ---------------------------------------------------------------------------

def test_expired_action_is_not_returned_as_pending() -> None:
    session = _make_session()
    manager = ConfirmationManager(session)

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

    assert manager.find_pending_action_by_confirmation("confirmo ejecutar act_deadbeef") is None

    expired_after = manager.find_action_by_id("act_deadbeef")
    assert expired_after is not None
    assert expired_after.status == "expired"


# ---------------------------------------------------------------------------
# 5. Multiple pending actions
# ---------------------------------------------------------------------------

def test_multiple_pending_actions_exact_confirmation_still_works() -> None:
    session = _make_session()
    manager = ConfirmationManager(session)

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

    assert manager.has_multiple_active_pending_actions()

    found_a = manager.find_pending_action_by_confirmation(multi_a.confirmation_phrase)
    assert found_a is not None
    assert found_a.id == multi_a.id

    found_b = manager.find_pending_action_by_confirmation(multi_b.confirmation_phrase)
    assert found_b is not None
    assert found_b.id == multi_b.id


def test_multiple_pending_generic_confirmation_route_invariant() -> None:
    """routes_chat must reject generic confirmation when multiple actions are pending."""
    session = _make_session()
    manager = ConfirmationManager(session)

    manager.create_pending_action(
        action_type="file", risk_level="critical", summary="A",
        payload={"action": "write_file", "path": "config/x.txt", "content": "x"},
        trace_id="trc_multi_inv",
    )
    manager.create_pending_action(
        action_type="file", risk_level="critical", summary="B",
        payload={"action": "write_file", "path": "config/y.txt", "content": "y"},
        trace_id="trc_multi_inv",
    )

    assert (
        manager.has_multiple_active_pending_actions()
        and manager.is_generic_confirmation_message("sí, hazlo")
    )
