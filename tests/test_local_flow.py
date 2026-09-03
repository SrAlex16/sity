"""Tests for ChatLocalFlow.try_handle — model router integration.

Uses stub ConfirmationManager so no DB is required for these tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


@pytest.fixture(autouse=True)
def _patch_settings_service():
    """SettingsService is called in the affirmative path to read model_upgrade_ttl_hours.

    These tests use MagicMock sessions (no real DB by design). Patch SettingsService
    to return default VoiceSettings so the TTL read doesn't hit the MagicMock session.
    """
    from app.settings.schemas import VoiceSettings
    with patch("app.settings.settings_service.SettingsService") as mock_svc:
        mock_svc.return_value.get_voice_settings.return_value = VoiceSettings()
        yield


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


def test_affirmative_persists_confirmation_message():
    """The 'Sí' confirmation is saved to DB so the chat history stays coherent."""
    ctx = _ctx("sí")
    set_proposal(_active_proposal())
    _flow().try_handle(ctx)
    ctx.save_message.assert_called_once_with(
        role="user", text="sí", trace_id="trc_test"
    )


def test_affirmative_propagates_selected_tools():
    """LocalFlowSignal carries the toolset from the proposal."""
    _tools = [{"name": "update_personality_settings"}, {"name": "no_action_required"}]
    from app.chat.model_router import ModelUpgradeProposal
    proposal = ModelUpgradeProposal(
        original_message="ponle más calidez",
        strong_model="claude-sonnet-4-6",
        reason="test",
        selected_tools=_tools,
    )
    set_proposal(proposal)
    result = _flow().try_handle(_ctx("sí"))
    assert isinstance(result, LocalFlowSignal)
    assert result.selected_tools == _tools


def test_affirmative_clears_proposal():
    from app.chat.model_router import get_proposal
    set_proposal(_active_proposal())
    _flow().try_handle(_ctx("sí"))
    assert get_proposal() is None


def test_affirmative_records_accepted_upgrade_category():
    from app.chat.model_router import get_accepted_upgrade_category, _session_accepted_upgrade_types
    _session_accepted_upgrade_types.clear()
    proposal = ModelUpgradeProposal(
        original_message="sube el sarcasmo",
        strong_model="claude-sonnet-4-6",
        reason="ajuste de personalidad — parámetros de sarcasmo",
    )
    set_proposal(proposal)
    ctx = _ctx("sí")
    ctx.session_id = "session_test_record"
    _flow().try_handle(ctx)
    assert get_accepted_upgrade_category("session_test_record") == "personality"


def test_affirmative_auto_accept_different_session_is_isolated():
    from app.chat.model_router import get_accepted_upgrade_category, _session_accepted_upgrade_types
    _session_accepted_upgrade_types.clear()
    set_proposal(_active_proposal())
    ctx = _ctx("sí")
    ctx.session_id = "session_a"
    _flow().try_handle(ctx)
    assert get_accepted_upgrade_category("session_b") is None


# ---------------------------------------------------------------------------
# Negative response → model_upgrade_rejected signal, re-run with current model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", ["no", "no gracias", "usa haiku", "quédate en haiku", "no hace falta"])
def test_negative_returns_rejected_signal(msg: str):
    set_proposal(_active_proposal())
    result = _flow().try_handle(_ctx(msg))
    assert isinstance(result, LocalFlowSignal)
    assert result.kind == "model_upgrade_rejected"
    assert result.original_message == "analiza este sistema complejo"


def test_negative_rejected_signal_carries_original_message():
    set_proposal(_active_proposal())
    result = _flow().try_handle(_ctx("no"))
    assert isinstance(result, LocalFlowSignal)
    assert result.original_message == "analiza este sistema complejo"
    assert result.strong_model == "claude-sonnet-4-6"


def test_negative_persists_rejection_message():
    """The 'no' message is saved to DB so chat history is coherent."""
    ctx = _ctx("no gracias")
    set_proposal(_active_proposal())
    _flow().try_handle(ctx)
    ctx.save_message.assert_called_once_with(
        role="user", text="no gracias", trace_id="trc_test"
    )


def test_negative_does_not_save_canned_sity_response():
    """No canned 'Vale, lo intento con el modelo actual.' is persisted — the
    real re-run will produce the actual response."""
    ctx = _ctx("no")
    set_proposal(_active_proposal())
    _flow().try_handle(ctx)
    calls = ctx.save_message.call_args_list
    sity_saves = [c for c in calls if c.kwargs.get("role") == "sity" or
                  (c.args and c.args[0] == "sity")]
    assert sity_saves == [], "No sity message should be saved on rejection — re-run produces the real one"


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


# ---------------------------------------------------------------------------
# propose_model_upgrade tool description guardrails (static, no API)
# ---------------------------------------------------------------------------

def test_propose_model_upgrade_description_forbids_personality_adjustments():
    """Tool description must explicitly prohibit personality-parameter changes."""
    from app.cortex.tool_schemas.actions import PROPOSE_MODEL_UPGRADE_TOOL
    desc = PROPOSE_MODEL_UPGRADE_TOOL["description"]
    assert "update_personality_settings" in desc, (
        "Tool description must name update_personality_settings as the correct tool "
        "for personality adjustments, so the planner knows not to propose an upgrade."
    )
    assert "personalidad" in desc.lower() or "sarcasmo" in desc.lower(), (
        "Tool description must mention personality parameters explicitly."
    )


def test_propose_model_upgrade_description_forbids_conversational_messages():
    """Tool description must explicitly prohibit purely conversational messages."""
    from app.cortex.tool_schemas.actions import PROPOSE_MODEL_UPGRADE_TOOL
    desc = PROPOSE_MODEL_UPGRADE_TOOL["description"].lower()
    conversational_guard = (
        "conversacional" in desc
        or "confirmaciones" in desc
        or "comentarios informales" in desc
    )
    assert conversational_guard, (
        "Tool description must explicitly ban purely conversational messages "
        "(confirmations of something already done, casual comments, etc.)."
    )


# ---------------------------------------------------------------------------
# turn_runner: model_upgrade_rejected triggers a real re-run
# ---------------------------------------------------------------------------

def test_rejected_signal_triggers_rerun_with_original_message():
    """When local_flow returns model_upgrade_rejected, turn_runner must call
    _chat_message_inner with the original_message — not hang."""
    from unittest.mock import patch, MagicMock
    from app.chat.model_router import LocalFlowSignal, ModelUpgradeProposal
    from app.api.schemas import ChatMessageResponse, UsageSummary

    rejected_signal = LocalFlowSignal(
        kind="model_upgrade_rejected",
        original_message="sube el sarcasmo al máximo",
        strong_model="claude-sonnet-4-6",
    )
    real_response = ChatMessageResponse(
        ok=True, trace_id="trc_rerun", text="Hecho.",
        provider="anthropic", model="claude-haiku-4-5-20251001",
        fallback_used=False, error_type=None,
        usage=UsageSummary(input_tokens=10, output_tokens=5, total_tokens=15,
                           daily_used_tokens=0, daily_budget_tokens=100_000, daily_ratio=0.0),
        warnings=[], personality_updated=False,
        updated_parameter=None, updated_parameters=[], artifacts=[],
    )

    call_log: list[str] = []

    def _fake_inner(request, session, **kwargs):
        call_log.append(request.message)
        if kwargs.get("_skip_history_turns", 0) == 3:
            return real_response
        return rejected_signal

    with patch("app.chat.turn_runner._chat_message_inner", side_effect=_fake_inner), \
         patch("app.chat.turn_runner.publish_event_sync"), \
         patch("app.chat.turn_runner.write_log"), \
         patch("app.chat.turn_runner.Session"):
        from app.chat.turn_runner import _run_turn_in_background
        from app.api.schemas import ChatMessageRequest
        req = ChatMessageRequest(
            message="no",
            client_turn_id="turn_test",
            session_id="user:1",
        )
        _run_turn_in_background(req, "turn_test", "user:1")

    assert "sube el sarcasmo al máximo" in call_log, (
        "turn_runner must re-run the original message after upgrade rejection; "
        f"actual calls: {call_log}"
    )
