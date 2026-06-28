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


def _snippet_html(snippet: str, url: str = "https://example.com") -> str:
    return f'<a class="result__snippet" href="{url}">{snippet}</a>'


def _mock_client(html: str = "", error: Exception | None = None) -> MagicMock:
    mc = MagicMock()
    mc.__enter__ = MagicMock(return_value=mc)
    mc.__exit__ = MagicMock(return_value=False)
    if error:
        mc.post.side_effect = error
    else:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        mc.post.return_value = mock_resp
    return mc


def test_web_search_registered() -> None:
    assert has_handler("web_search")


def test_web_search_empty_query_returns_error() -> None:
    result = dispatch_tool(_ctx(query=""))
    assert result.ok is False
    assert "consulta" in result.raw_result["text"].lower() or "query" in result.message.lower()


def test_web_search_calls_duckduckgo() -> None:
    mc = _mock_client(_snippet_html("Python es un lenguaje de programación."))

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="python lenguaje"))

    assert result.ok is True
    call_args = mc.post.call_args
    assert "duckduckgo.com" in call_args[0][0]
    assert call_args[1]["data"]["q"] == "python lenguaje"


def test_web_search_parses_abstract_text() -> None:
    html = _snippet_html("Python es un lenguaje de programación de alto nivel.", "https://python.org")
    mc = _mock_client(html)

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="python"))

    assert result.ok is True
    assert "Python es un lenguaje" in result.raw_result["text"]
    assert "Resultados para" in result.raw_result["text"]


def test_web_search_filters_ads() -> None:
    html = (
        _snippet_html("Anuncio de algo.", "https://y.js?ad=1")
        + _snippet_html("Resultado orgánico.", "https://organico.com")
    )
    mc = _mock_client(html)

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="algo"))

    assert result.ok is True
    assert "Anuncio" not in result.raw_result["text"]
    assert "Resultado orgánico" in result.raw_result["text"]


def test_web_search_handles_http_error() -> None:
    mc = _mock_client(error=Exception("connection refused"))

    with patch("app.tools.handlers.web_search_tools.httpx.Client", return_value=mc):
        result = dispatch_tool(_ctx(query="algo"))

    assert result.ok is False
    assert "Error" in result.raw_result["text"]
    assert result.raw_result["success"] is False
