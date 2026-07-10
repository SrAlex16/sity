"""Tests for POST /debug/frontend-error."""
from __future__ import annotations

from unittest.mock import call, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_URL = "/debug/frontend-error"


def test_full_report_returns_ok() -> None:
    with patch("app.api.routes_debug.write_log") as mock_log:
        resp = client.post(_URL, json={
            "message": "Uncaught TypeError: cannot read properties of null",
            "stack": "TypeError\n  at App.tsx:42",
            "url": "https://sity.aletm.com/",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_log.assert_called_once()
    kw = mock_log.call_args.kwargs
    assert kw["level"] == "WARN"
    assert kw["module"] == "frontend"
    assert kw["event"] == "frontend_error"
    assert "message" in kw["payload"]
    assert "stack" in kw["payload"]
    assert "url" in kw["payload"]


def test_minimal_report_message_only() -> None:
    with patch("app.api.routes_debug.write_log") as mock_log:
        resp = client.post(_URL, json={"message": "ReferenceError: x is not defined"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    kw = mock_log.call_args.kwargs
    assert kw["payload"]["message"] == "ReferenceError: x is not defined"
    assert "stack" not in kw["payload"]
    assert "url" not in kw["payload"]


def test_long_message_truncated_to_500() -> None:
    long_msg = "x" * 1000
    with patch("app.api.routes_debug.write_log") as mock_log:
        resp = client.post(_URL, json={"message": long_msg})
    assert resp.status_code == 200
    assert len(mock_log.call_args.kwargs["payload"]["message"]) == 500


def test_long_stack_truncated_to_2000() -> None:
    long_stack = "at file.js:1\n" * 300
    with patch("app.api.routes_debug.write_log") as mock_log:
        resp = client.post(_URL, json={"message": "err", "stack": long_stack})
    assert resp.status_code == 200
    assert len(mock_log.call_args.kwargs["payload"]["stack"]) == 2000


def test_missing_message_returns_422() -> None:
    resp = client.post(_URL, json={"stack": "at file.js:1"})
    assert resp.status_code == 422
