"""Tests unitarios para ChatPreAIFlow — los tres gates pre-AI."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.pre_ai_flow import ChatPreAIFlow


_MODULE = "app.chat.pre_ai_flow"


def _make_request(message: str = "hola") -> ChatMessageRequest:
    return ChatMessageRequest(
        message=message,
        history=[],
        input_mode="text",
        client_turn_id=None,
        source_channel="web",
    )


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.trace_id = "trc_test"
    ctx.daily_budget = 1_000_000
    ctx.warning_threshold = 0.80
    ctx.critical_threshold = 0.95
    ctx.persistence.save = MagicMock()
    return ctx


def _fake_response() -> MagicMock:
    r = MagicMock(spec=ChatMessageResponse)
    r.ok = True
    return r


def _make_flow(session: MagicMock, ctx: MagicMock) -> ChatPreAIFlow:
    with patch(f"{_MODULE}.ConfirmationManager"), \
         patch(f"{_MODULE}.ChatLocalFlow"), \
         patch(f"{_MODULE}.get_runtime_config"):
        return ChatPreAIFlow(session=session, ctx=ctx)


# ---------------------------------------------------------------------------

def test_pre_ai_flow_returns_local_flow_response() -> None:
    """Si local_flow maneja el mensaje, try_handle devuelve su respuesta."""
    ctx = _make_ctx()
    flow = _make_flow(MagicMock(), ctx)

    expected = _fake_response()
    flow.local_flow.try_handle.return_value = expected

    result = flow.try_handle(_make_request("cancela"))

    assert result is expected
    flow.local_flow.try_handle.assert_called_once()


def test_pre_ai_flow_returns_pending_action_response() -> None:
    """Si hay pending action confirmada, try_handle la ejecuta y devuelve respuesta."""
    ctx = _make_ctx()
    flow = _make_flow(MagicMock(), ctx)

    flow.local_flow.try_handle.return_value = None

    fake_action = MagicMock()
    flow.confirmation_manager.find_pending_action_by_confirmation.return_value = fake_action
    flow.confirmation_manager.find_pending_action_by_context.return_value = None

    expected = _fake_response()

    with patch(f"{_MODULE}.PendingActionRunner") as mock_par_cls:
        mock_par_cls.return_value.run.return_value = expected
        result = flow.try_handle(_make_request("confirmo ejecutar act_aabbccdd"))

    assert result is expected
    mock_par_cls.return_value.run.assert_called_once()
    # first arg is the pending action
    assert mock_par_cls.return_value.run.call_args[0][0] is fake_action


def test_pre_ai_flow_returns_budget_guard_response() -> None:
    """Si el presupuesto está agotado, try_handle devuelve respuesta de budget."""
    ctx = _make_ctx()
    flow = _make_flow(MagicMock(), ctx)

    flow.local_flow.try_handle.return_value = None
    flow.confirmation_manager.find_pending_action_by_confirmation.return_value = None
    flow.confirmation_manager.find_pending_action_by_context.return_value = None

    expected = _fake_response()

    with patch(f"{_MODULE}.ChatBudgetGuard") as mock_guard_cls:
        mock_guard_cls.return_value.try_handle.return_value = expected
        result = flow.try_handle(_make_request("cuánto queda de presupuesto"))

    assert result is expected
    mock_guard_cls.return_value.try_handle.assert_called_once()


def test_pre_ai_flow_returns_none_when_no_gate_matches() -> None:
    """Si ningún gate maneja el mensaje, try_handle devuelve None."""
    ctx = _make_ctx()
    flow = _make_flow(MagicMock(), ctx)

    flow.local_flow.try_handle.return_value = None
    flow.confirmation_manager.find_pending_action_by_confirmation.return_value = None
    flow.confirmation_manager.find_pending_action_by_context.return_value = None

    with patch(f"{_MODULE}.ChatBudgetGuard") as mock_guard_cls:
        mock_guard_cls.return_value.try_handle.return_value = None
        result = flow.try_handle(_make_request("qué hora es"))

    assert result is None
