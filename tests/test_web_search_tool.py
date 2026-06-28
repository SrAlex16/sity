"""Tests for web_search tool handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import app.tools.handlers  # noqa: F401 — ensures handlers are registered
from app.tools.registry import ToolContext, dispatch_tool, has_handler


def _ctx(query: str = "") -> ToolContext:
    return ToolContext(
        tool_name="web_search",
        tool_input={"query": query},
        trace_id="trc_test_web_search",
        executor=MagicMock(),
    )


def _html_with_results(title: str, snippet: str, url: str = "https://example.com") -> str:
    return (
        f'<a class="result__a" href="//duckduckgo.com/l/?uddg={url}">{title}</a>'
        f'<a class="result__snippet">{snippet}</a>'
    )


def _mock_post_response(html: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html
    return mock_resp


def _mock_client(html: str = "") -> MagicMock:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = _mock_post_response(html)
    return mock_client


def test_web_search_registered() -> None:
    assert has_handler("web_search")


def test_web_search_empty_query_returns_error() -> None:
    result = dispatch_tool(_ctx(query=""))
    assert result.ok is False
    assert "consulta" in result.raw_result["text"].lower() or "query" in result.message.lower()


def test_web_search_calls_duckduckgo() -> None:
    mc = _mock_client(_html_with_results("Python", "Lenguaje de programación."))

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="python lenguaje"))

    assert result.ok is True
    call_args = mc.post.call_args
    called_url = call_args[0][0]
    called_data = call_args[1]["data"]
    assert "duckduckgo.com" in called_url
    assert called_data["q"] == "python lenguaje"


def test_web_search_parses_abstract_text() -> None:
    html = _html_with_results("Python", "Python es un lenguaje de programación de alto nivel.")
    mc = _mock_client(html)

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="python"))

    assert result.ok is True
    assert "Python es un lenguaje" in result.raw_result["text"]
    assert "Resultados de búsqueda" in result.raw_result["text"]


def test_web_search_handles_http_error() -> None:
    mc = MagicMock()
    mc.__enter__ = MagicMock(return_value=mc)
    mc.__exit__ = MagicMock(return_value=False)
    mc.post.side_effect = Exception("connection refused")

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="algo"))

    assert result.ok is False
    assert "Error" in result.raw_result["text"]
    assert result.raw_result["success"] is False
