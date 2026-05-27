"""Tests for app.core.cors_config.

parse_cors_origins is a pure function — no env, no side-effects.
get_cors_origins reads env vars on every call, so monkeypatching works.

The CORS middleware integration test constructs a minimal FastAPI app
after the env var is set, because main.py calls get_cors_origins() at
module load time (app already initialised in other tests).
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.cors_config import _BUILTIN_DEFAULTS, get_cors_origins, parse_cors_origins


# ---------------------------------------------------------------------------
# parse_cors_origins — pure function
# ---------------------------------------------------------------------------

def test_empty_raw_returns_defaults():
    result = parse_cors_origins("")
    assert result == list(_BUILTIN_DEFAULTS)


def test_single_extra_origin_appended():
    result = parse_cors_origins("http://192.168.1.133:5174")
    assert "http://192.168.1.133:5174" in result
    assert result.index("http://localhost:5173") < result.index("http://192.168.1.133:5174")


def test_multiple_origins_comma_separated():
    result = parse_cors_origins("http://a.example.com,http://b.example.com")
    assert "http://a.example.com" in result
    assert "http://b.example.com" in result


def test_whitespace_stripped():
    result = parse_cors_origins("  http://a.example.com ,  http://b.example.com  ")
    assert "http://a.example.com" in result
    assert "http://b.example.com" in result


def test_empty_tokens_discarded():
    result = parse_cors_origins("http://a.example.com,,http://b.example.com,")
    assert "" not in result
    assert "http://a.example.com" in result
    assert "http://b.example.com" in result


def test_no_duplicates_when_default_in_raw():
    """Adding a default origin again must not produce duplicates."""
    result = parse_cors_origins("http://localhost:5173,http://extra.com")
    assert result.count("http://localhost:5173") == 1


def test_defaults_always_first():
    result = parse_cors_origins("http://extra.com")
    assert result[0] == "http://localhost:5173"
    assert result[1] == "http://127.0.0.1:5173"


def test_custom_defaults_used():
    result = parse_cors_origins("http://extra.com", defaults=["http://custom:8080"])
    assert result == ["http://custom:8080", "http://extra.com"]


def test_custom_defaults_no_builtin_defaults():
    """When defaults kwarg is passed, built-in defaults are NOT included."""
    result = parse_cors_origins("", defaults=["http://custom:8080"])
    assert "http://localhost:5173" not in result


def test_returns_list():
    assert isinstance(parse_cors_origins(""), list)


def test_order_preserved_for_extra_origins():
    result = parse_cors_origins("http://z.com,http://a.com")
    z_idx = result.index("http://z.com")
    a_idx = result.index("http://a.com")
    assert z_idx < a_idx


# ---------------------------------------------------------------------------
# get_cors_origins — reads env vars
# ---------------------------------------------------------------------------

def test_get_cors_origins_no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SITY_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("SITY_CORS_ORIGIN", raising=False)
    result = get_cors_origins()
    assert result == list(_BUILTIN_DEFAULTS)


def test_get_cors_origins_plural_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_CORS_ORIGINS", "http://192.168.1.133:5174,http://192.168.1.133:5173")
    monkeypatch.delenv("SITY_CORS_ORIGIN", raising=False)
    result = get_cors_origins()
    assert "http://192.168.1.133:5174" in result
    assert "http://192.168.1.133:5173" in result
    # Built-in defaults still present
    assert "http://localhost:5173" in result


def test_get_cors_origins_singular_fallback(monkeypatch: pytest.MonkeyPatch):
    """Legacy SITY_CORS_ORIGIN (singular) used when plural is absent."""
    monkeypatch.delenv("SITY_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("SITY_CORS_ORIGIN", "http://legacy.example.com")
    result = get_cors_origins()
    assert "http://legacy.example.com" in result
    assert "http://localhost:5173" in result


def test_get_cors_origins_plural_takes_precedence(monkeypatch: pytest.MonkeyPatch):
    """SITY_CORS_ORIGINS wins over SITY_CORS_ORIGIN when both are set."""
    monkeypatch.setenv("SITY_CORS_ORIGINS", "http://plural.example.com")
    monkeypatch.setenv("SITY_CORS_ORIGIN", "http://singular.example.com")
    result = get_cors_origins()
    assert "http://plural.example.com" in result
    # singular is ignored when plural is set
    assert "http://singular.example.com" not in result


def test_get_cors_origins_whitespace_only_env_uses_fallback(monkeypatch: pytest.MonkeyPatch):
    """SITY_CORS_ORIGINS set to whitespace only falls back to singular var."""
    monkeypatch.setenv("SITY_CORS_ORIGINS", "   ")
    monkeypatch.setenv("SITY_CORS_ORIGIN", "http://fallback.example.com")
    result = get_cors_origins()
    assert "http://fallback.example.com" in result


def test_get_cors_origins_returns_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SITY_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("SITY_CORS_ORIGIN", raising=False)
    assert isinstance(get_cors_origins(), list)


# ---------------------------------------------------------------------------
# Middleware integration — minimal FastAPI app built after env is set
#
# We cannot test this via app.main because main.py calls get_cors_origins()
# at import time (module-level add_middleware).  Instead we build a tiny
# test app here — same pattern CORSMiddleware would use in production.
# ---------------------------------------------------------------------------

def _make_cors_app(origins: list[str]) -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @test_app.get("/ping")
    def ping():
        return {"ok": True}

    return test_app


def test_middleware_allows_configured_origin():
    """CORSMiddleware built with get_cors_origins() allows declared origins."""
    origins = ["http://localhost:5173", "http://192.168.1.133:5174"]
    test_app = _make_cors_app(origins)

    with TestClient(test_app, raise_server_exceptions=True) as client:
        resp = client.options(
            "/ping",
            headers={
                "Origin": "http://192.168.1.133:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://192.168.1.133:5174"


def test_middleware_blocks_unknown_origin():
    """CORSMiddleware built with get_cors_origins() blocks unknown origins."""
    origins = ["http://localhost:5173"]
    test_app = _make_cors_app(origins)

    with TestClient(test_app, raise_server_exceptions=True) as client:
        resp = client.options(
            "/ping",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    # No ACAO header → blocked
    assert "access-control-allow-origin" not in resp.headers


def test_middleware_env_origins_passed_correctly(monkeypatch: pytest.MonkeyPatch):
    """Origins from get_cors_origins() reach CORSMiddleware correctly."""
    monkeypatch.setenv("SITY_CORS_ORIGINS", "http://mydevbox:5174")
    monkeypatch.delenv("SITY_CORS_ORIGIN", raising=False)

    origins = get_cors_origins()
    assert "http://mydevbox:5174" in origins

    test_app = _make_cors_app(origins)
    with TestClient(test_app, raise_server_exceptions=True) as client:
        resp = client.options(
            "/ping",
            headers={
                "Origin": "http://mydevbox:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.headers.get("access-control-allow-origin") == "http://mydevbox:5174"
