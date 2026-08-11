"""Tests for GET /settings/ui-language-suggestion (Sistema 1 — UI language via CF-IPCountry).

Coverage:
  - Known Spanish-speaking country → 'es'
  - Known English-speaking country → 'en'
  - Japanese country → 'ja'
  - Country mapped to unsupported lang (FR → 'fr') → 'en' fallback
  - Unknown country → 'en' fallback
  - Missing CF-IPCountry header → 'en' fallback (safe default)
  - Accessible without authentication (guests, unauthenticated)
  - Response shape: {lang: str, country: str | None}
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _suggest(client: TestClient, country: str | None) -> dict:
    headers = {"cf-ipcountry": country} if country is not None else {}
    resp = client.get("/settings/ui-language-suggestion", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Country → known supported language ──────────────────────────────────────

def test_spain_returns_es(client: TestClient) -> None:
    assert _suggest(client, "ES")["lang"] == "es"


def test_mexico_returns_es(client: TestClient) -> None:
    assert _suggest(client, "MX")["lang"] == "es"


def test_argentina_returns_es(client: TestClient) -> None:
    assert _suggest(client, "AR")["lang"] == "es"


def test_us_returns_en(client: TestClient) -> None:
    assert _suggest(client, "US")["lang"] == "en"


def test_gb_returns_en(client: TestClient) -> None:
    assert _suggest(client, "GB")["lang"] == "en"


def test_japan_returns_ja(client: TestClient) -> None:
    assert _suggest(client, "JP")["lang"] == "ja"


# ── Fallbacks ────────────────────────────────────────────────────────────────

def test_unsupported_mapped_lang_falls_back_to_en(client: TestClient) -> None:
    # FR maps to 'fr' which has no translations yet → fallback to 'en'
    assert _suggest(client, "FR")["lang"] == "en"


def test_unknown_country_falls_back_to_en(client: TestClient) -> None:
    assert _suggest(client, "XX")["lang"] == "en"


def test_empty_header_falls_back_to_en(client: TestClient) -> None:
    assert _suggest(client, "")["lang"] == "en"


def test_missing_header_falls_back_to_en(client: TestClient) -> None:
    assert _suggest(client, None)["lang"] == "en"


# ── Response shape ───────────────────────────────────────────────────────────

def test_response_has_lang_and_country(client: TestClient) -> None:
    data = _suggest(client, "JP")
    assert "lang" in data
    assert "country" in data
    assert data["country"] == "JP"


def test_missing_header_country_is_none(client: TestClient) -> None:
    data = _suggest(client, None)
    assert data["country"] is None


# ── No auth required ─────────────────────────────────────────────────────────

def test_accessible_without_cookie(client: TestClient) -> None:
    resp = client.get("/settings/ui-language-suggestion", headers={"cf-ipcountry": "ES"})
    assert resp.status_code == 200
