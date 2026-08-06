"""Tests for the read_webpage tool handler.

Coverage:
- Happy path: HTML content is extracted as plain text and wrapped with untrusted-content header
- Wrapper de contenido no confiable presente en la respuesta
- Contenido truncado a 5000 chars; nota de truncado añadida
- Timeout devuelve ok=False con mensaje descriptivo
- IP privada/localhost bloqueada (SSRF guard)
- Content-type binario rechazado sin descargar el body
- URL sin esquema http/https rechazada
- URL vacía rechazada
- Logging del dominio con event="read_webpage_domain"
- Tool registrada en has_handler
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.tool_executor import ToolExecutor
from app.memory.db import engine
from app.tools.registry import ToolContext, dispatch_tool, has_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(url: str, session_id: str = "user:1") -> ToolContext:
    from sqlmodel import Session
    with Session(engine) as db:
        executor = ToolExecutor(db, session_id=session_id)
        return ToolContext(
            tool_name="read_webpage",
            tool_input={"url": url},
            trace_id="trc_rwp_test",
            executor=executor,
        )


def _make_http_response(text: str, status: int = 200, content_type: str = "text/html; charset=utf-8"):
    """Build a minimal mock httpx response."""
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    mock.headers = {"content-type": content_type}
    mock.raise_for_status = MagicMock()
    if status >= 400:
        import httpx
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=mock,
        )
    return mock


def _make_head_response(content_type: str = "text/html"):
    mock = MagicMock()
    mock.headers = {"content-type": content_type}
    return mock


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_read_webpage_registered(self) -> None:
        assert has_handler("read_webpage")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_extracts_text_from_html(self) -> None:
        html = "<html><body><h1>Título</h1><p>Párrafo de prueba.</p></body></html>"
        head_resp = _make_head_response("text/html")
        get_resp = _make_http_response(html)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/articulo"))

        assert result.ok is True
        assert "Título" in result.raw_result["text"]
        assert "Párrafo de prueba." in result.raw_result["text"]

    def test_untrusted_content_wrapper_present(self) -> None:
        html = "<p>Contenido</p>"
        head_resp = _make_head_response()
        get_resp = _make_http_response(html)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/page"))

        text = result.raw_result["text"]
        assert "contenido de terceros" in text.lower()
        assert "no instrucciones" in text.lower()

    def test_script_and_style_stripped(self) -> None:
        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert('xss')</script><p>Solo texto</p></body></html>"
        )
        head_resp = _make_head_response()
        get_resp = _make_http_response(html)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/page"))

        text = result.raw_result["text"]
        assert "alert" not in text
        assert "color:red" not in text
        assert "Solo texto" in text


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

class TestTruncation:
    def test_content_truncated_to_5000_chars(self) -> None:
        long_content = "A" * 10_000
        html = f"<p>{long_content}</p>"
        head_resp = _make_head_response()
        get_resp = _make_http_response(html)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/long"))

        text = result.raw_result["text"]
        # Count 'A' characters in result — must not exceed 5000 (the truncation limit)
        a_count = text.count("A")
        assert a_count <= 5_000, f"Extracted {a_count} 'A' chars, expected ≤ 5000"
        assert a_count > 0, "Expected some 'A' chars in extracted text"
        assert "truncado" in text.lower()

    def test_short_content_not_truncated(self) -> None:
        html = "<p>Texto corto.</p>"
        head_resp = _make_head_response()
        get_resp = _make_http_response(html)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/short"))

        assert "truncado" not in result.raw_result["text"].lower()


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

class TestSSRFGuard:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/secret",
        "http://localhost/admin",
        "http://192.168.1.1/",
        "http://10.0.0.1/internal",
        "http://172.16.0.1/metadata",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata endpoint
    ])
    def test_private_ips_blocked(self, url: str) -> None:
        result = dispatch_tool(_ctx(url))
        assert result.ok is False
        assert "privada" in result.message.lower() or "interna" in result.message.lower()

    def test_ssrf_guard_checks_resolved_ip(self) -> None:
        # Even if hostname looks public, if it resolves to a private IP → blocked.
        # We patch _is_private_ip directly to simulate DNS-rebinding scenario.
        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=True):
            result = dispatch_tool(_ctx("https://evil.example.com/redirect"))
        assert result.ok is False


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

class TestURLValidation:
    def test_empty_url_rejected(self) -> None:
        result = dispatch_tool(_ctx(""))
        assert result.ok is False

    def test_non_http_scheme_rejected(self) -> None:
        result = dispatch_tool(_ctx("ftp://files.example.com/data.txt"))
        assert result.ok is False
        assert "esquema" in result.message.lower()

    def test_file_scheme_rejected(self) -> None:
        result = dispatch_tool(_ctx("file:///etc/passwd"))
        assert result.ok is False


# ---------------------------------------------------------------------------
# Content-type guard
# ---------------------------------------------------------------------------

class TestContentTypeGuard:
    @pytest.mark.parametrize("ct", [
        "application/octet-stream",
        "application/pdf",
        "application/zip",
    ])
    def test_binary_content_type_rejected(self, ct: str) -> None:
        head_resp = _make_head_response(ct)

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/file.bin"))

        assert result.ok is False
        assert "contenido" in result.message.lower() or "tipo" in result.message.lower()

    def test_text_html_accepted(self) -> None:
        head_resp = _make_head_response("text/html; charset=utf-8")
        get_resp = _make_http_response("<p>OK</p>")

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://example.com/page"))

        assert result.ok is True


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_returns_error(self) -> None:
        import httpx

        # HEAD succeeds with empty content-type; GET raises TimeoutException
        head_resp = _make_head_response("")
        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            mock_client_cls.return_value = mock_client

            result = dispatch_tool(_ctx("https://slow.example.com/"))

        assert result.ok is False
        assert "timeout" in result.message.lower()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_domain_logged_on_success(self) -> None:
        html = "<p>Contenido</p>"
        head_resp = _make_head_response()
        get_resp = _make_http_response(html)
        logged_events: list[dict] = []

        def capture_log(**kwargs: object) -> None:
            logged_events.append(dict(kwargs))

        with patch("app.tools.handlers.web_fetch_tools._is_private_ip", return_value=False), \
             patch("httpx.Client") as mock_client_cls, \
             patch("app.tools.handlers.web_fetch_tools.write_log", side_effect=capture_log):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = head_resp
            mock_client.get.return_value = get_resp
            mock_client_cls.return_value = mock_client

            dispatch_tool(_ctx("https://example.com/article"))

        domain_events = [e for e in logged_events if e.get("event") == "read_webpage_domain"]
        assert len(domain_events) == 1
        assert domain_events[0]["payload"]["domain"] == "example.com"
