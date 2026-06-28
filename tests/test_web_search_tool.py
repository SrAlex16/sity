"""Tests for web_search tool handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.tools.handlers  # noqa: F401 — ensures handlers are registered
from app.tools.registry import ToolContext, dispatch_tool, has_handler


def _ctx(query: str = "") -> ToolContext:
    return ToolContext(
        tool_name="web_search",
        tool_input={"query": query},
        trace_id="trc_test_web_search",
        executor=MagicMock(),
    )


def _mock_ddg_response(abstract_text: str = "", related: list | None = None) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "AbstractText": abstract_text,
        "AbstractURL": "https://example.com" if abstract_text else "",
        "RelatedTopics": related or [],
    }
    return mock_resp


def test_web_search_registered() -> None:
    assert has_handler("web_search")


def test_web_search_empty_query_returns_error() -> None:
    result = dispatch_tool(_ctx(query=""))
    assert result.ok is False
    assert "consulta" in result.raw_result["text"].lower() or "query" in result.message.lower()


def test_web_search_calls_duckduckgo() -> None:
    mock_resp = _mock_ddg_response("Texto de prueba.")
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mock_client):
        result = dispatch_tool(_ctx(query="python lenguaje"))

    assert result.ok is True
    call_args = mock_client.get.call_args_list[0]
    called_url = call_args[0][0]
    called_params = call_args[1]["params"]
    assert "duckduckgo.com" in called_url
    assert called_params["q"] == "python lenguaje"
    assert called_params["format"] == "json"


def test_web_search_parses_abstract_text() -> None:
    mock_resp = _mock_ddg_response("Python es un lenguaje de programación.")
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mock_client):
        result = dispatch_tool(_ctx(query="python"))

    assert result.ok is True
    assert "Python es un lenguaje" in result.raw_result["text"]
    assert "Resumen:" in result.raw_result["text"]


def test_web_search_handles_http_error() -> None:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = Exception("connection refused")

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mock_client):
        result = dispatch_tool(_ctx(query="algo"))

    assert result.ok is False
    assert "Error" in result.raw_result["text"]
    assert result.raw_result["success"] is False
