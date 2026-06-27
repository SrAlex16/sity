"""Tests for ChatLocalFlow.try_handle — model router integration.

Uses stub ConfirmationManager so no DB is required for these tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.chat.local_flow import ChatLocalFlow, LocalFlowContext
from app.chat.model_router import (
    LocalFlowSignal,
    ModelUpgradeProposal,
    clear_proposal,
    set_proposal,
)
from app.api.schemas import ChatMessageResponse


def _ctx(message: str) -> LocalFlowContext:
    save_fn = MagicMock()
    get_usage_fn = MagicMock(return_value=0)
    session = MagicMock()
    return LocalFlowContext(
        session=session,
        trace_id="trc_test",
        message=message,
        daily_budget=100_000,
        warnings=[],
        save_message=save_fn,
        get_usage=get_usage_fn,
    )


def _flow() -> ChatLocalFlow:
    cm = MagicMock()
    cm.extract_action_id_from_message.return_value = None
    cm.find_pending_action_by_confirmation.return_value = None
    cm.has_multiple_active_pending_actions.return_value = False
    cm.is_generic_confirmation_message.return_value = False
    cm.find_pending_action_by_context.return_value = None
    return ChatLocalFlow(confirmation_manager=cm)


def setup_function():
    clear_proposal()


def teardown_function():
    clear_proposal()


def _active_proposal() -> ModelUpgradeProposal:
    return ModelUpgradeProposal(
        original_message="analiza este sistema complejo",
        strong_model="claude-sonnet-4-6",
        reason="múltiples archivos y trazas largas",
    )


# ---------------------------------------------------------------------------
# Affirmative response → model_upgrade_accepted signal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", ["sí", "si", "vale", "ok", "adelante", "sí, úsalo", "usa sonnet"])
def test_affirmative_returns_model_upgrade_accepted(msg: str):
    set_proposal(_active_proposal())
    result = _flow().try_handle(_ctx(msg))
    assert isinstance(result, LocalFlowSignal)
    assert result.kind == "model_upgrade_accepted"
    assert result.original_message == "analiza este sistema complejo"
    assert result.strong_model == "claude-sonnet-4-6"


def test_affirmative_clears_proposal():
    from app.chat.model_router import get_proposal
    set_proposal(_active_proposal())
    _flow().try_handle(_ctx("sí"))
    assert get_proposal() is None


# ---------------------------------------------------------------------------
# Negative response → local response, proposal cleared
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", ["no", "no gracias", "usa haiku", "quédate en haiku", "no hace falta"])
def test_negative_returns_local_response(msg: str):
    set_proposal(_active_proposal())
    result = _flow().try_handle(_ctx(msg))
    assert isinstance(result, ChatMessageResponse)
    assert "modelo actual" in result.text


def test_negative_clears_proposal():
    from app.chat.model_router import get_proposal
    set_proposal(_active_proposal())
    _flow().try_handle(_ctx("no"))
    assert get_proposal() is None


# ---------------------------------------------------------------------------
# Unrelated message → proposal discarded silently, normal flow resumes
# ---------------------------------------------------------------------------

def test_unrelated_message_discards_proposal_silently():
    from app.chat.model_router import get_proposal
    set_proposal(_active_proposal())
    result = _flow().try_handle(_ctx("cuéntame un chiste"))
    # Proposal cleared
    assert get_proposal() is None
    # No model-router response — falls through to normal flow (returns None here
    # because the stub ConfirmationManager has no pending actions)
    assert result is None


# ---------------------------------------------------------------------------
# No active proposal → normal flow unaffected
# ---------------------------------------------------------------------------

def test_no_proposal_passes_through_to_normal_flow():
    result = _flow().try_handle(_ctx("¿qué tal estás?"))
    assert result is None


# ---------------------------------------------------------------------------
# Expired proposal → treated as no proposal
# ---------------------------------------------------------------------------

def test_expired_proposal_passes_through():
    from datetime import datetime, timedelta
    expired = ModelUpgradeProposal(
        original_message="msg",
        strong_model="claude-sonnet-4-6",
        reason="r",
        created_at=datetime.utcnow() - timedelta(minutes=10),
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    set_proposal(expired)
    result = _flow().try_handle(_ctx("sí"))
    # Expired → not intercepted by router; falls through to normal flow
    assert not isinstance(result, LocalFlowSignal)


# ---------------------------------------------------------------------------
# sonnet_response dataset tag
# ---------------------------------------------------------------------------

def test_tag_sity_with_model_adds_sonnet_tag():
    import json
    from unittest.mock import MagicMock
    from app.chat.turn_persistence import ChatTurnPersistence
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService

    capture_ctx = DatasetCaptureContext(
        enabled=True,
        dataset_source="normal_use",
        dataset_eligible=True,
        dataset_tags=["existing_tag"],
    )
    capture_svc = MagicMock(spec=DatasetCaptureService)
    from app.memory.message_metadata import build_message_metadata
    capture_svc.build_user_metadata.return_value = build_message_metadata(role="user")
    capture_svc.build_sity_metadata.return_value = build_message_metadata(
        role="sity",
        dataset_source="normal_use",
        dataset_eligible=True,
        dataset_tags_json=json.dumps(["existing_tag"]),
    )

    session = MagicMock()
    persistence = ChatTurnPersistence(session, capture_ctx, capture_svc)
    persistence.tag_sity_with_model("claude-sonnet-4-6")

    tags = json.loads(persistence._sity_metadata.dataset_tags_json or "[]")
    assert "sonnet_response" in tags
    assert "existing_tag" in tags


def test_tag_sity_with_model_no_tag_for_haiku():
    import json
    from unittest.mock import MagicMock
    from app.chat.turn_persistence import ChatTurnPersistence
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService

    capture_ctx = DatasetCaptureContext(enabled=True, dataset_source="normal_use", dataset_eligible=True)
    capture_svc = MagicMock(spec=DatasetCaptureService)
    from app.memory.message_metadata import build_message_metadata
    capture_svc.build_user_metadata.return_value = build_message_metadata(role="user")
    capture_svc.build_sity_metadata.return_value = build_message_metadata(role="sity")

    session = MagicMock()
    persistence = ChatTurnPersistence(session, capture_ctx, capture_svc)
    persistence.tag_sity_with_model("claude-haiku-4-5-20251001")

    assert persistence._sity_metadata.dataset_tags_json is None


def test_tag_sity_with_model_idempotent():
    import json
    from unittest.mock import MagicMock
    from app.chat.turn_persistence import ChatTurnPersistence
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService

    capture_ctx = DatasetCaptureContext(enabled=True, dataset_source="normal_use", dataset_eligible=True)
    capture_svc = MagicMock(spec=DatasetCaptureService)
    from app.memory.message_metadata import build_message_metadata
    capture_svc.build_user_metadata.return_value = build_message_metadata(role="user")
    capture_svc.build_sity_metadata.return_value = build_message_metadata(role="sity")

    session = MagicMock()
    persistence = ChatTurnPersistence(session, capture_ctx, capture_svc)
    persistence.tag_sity_with_model("claude-sonnet-4-6")
    persistence.tag_sity_with_model("claude-sonnet-4-6")

    tags = json.loads(persistence._sity_metadata.dataset_tags_json or "[]")
    assert tags.count("sonnet_response") == 1
