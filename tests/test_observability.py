"""Tests for observability infrastructure: _redact_sensitive and purge_old_logs."""
from __future__ import annotations

import time
from pathlib import Path

from app.core.tool_executor import _redact_sensitive
from app.trace.logger import LOG_DIR, purge_old_logs


# ---------------------------------------------------------------------------
# _redact_sensitive
# ---------------------------------------------------------------------------

def test_redact_top_level_sensitive_keys():
    data = {"access_token": "abc123", "query": "hello"}
    result = _redact_sensitive(data)
    assert result["access_token"] == "***"
    assert result["query"] == "hello"


def test_redact_case_insensitive():
    data = {"Authorization": "Bearer xyz", "API_KEY": "key123", "Password": "s3cr3t"}
    result = _redact_sensitive(data)
    assert result["Authorization"] == "***"
    assert result["API_KEY"] == "***"
    assert result["Password"] == "***"


def test_redact_nested_dict():
    data = {
        "outer": "safe",
        "credentials": {
            "client_secret": "s3cr3t",
            "client_id": "pub123",
        },
    }
    result = _redact_sensitive(data)
    assert result["outer"] == "safe"
    assert result["credentials"]["client_secret"] == "***"
    assert result["credentials"]["client_id"] == "pub123"


def test_redact_list_of_dicts():
    data = [{"token": "t1", "name": "a"}, {"token": "t2", "name": "b"}]
    result = _redact_sensitive(data)
    assert result[0]["token"] == "***"
    assert result[0]["name"] == "a"
    assert result[1]["token"] == "***"


def test_redact_mixed_nested():
    data = {
        "items": [
            {"access_token": "abc", "label": "x"},
            {"safe_key": "value"},
        ],
        "meta": {"api_key": "key", "count": 5},
    }
    result = _redact_sensitive(data)
    assert result["items"][0]["access_token"] == "***"
    assert result["items"][0]["label"] == "x"
    assert result["items"][1]["safe_key"] == "value"
    assert result["meta"]["api_key"] == "***"
    assert result["meta"]["count"] == 5


def test_redact_non_dict_passthrough():
    assert _redact_sensitive("hello") == "hello"
    assert _redact_sensitive(42) == 42
    assert _redact_sensitive(None) is None
    assert _redact_sensitive([1, 2, 3]) == [1, 2, 3]


def test_redact_partial_key_match():
    # "refresh_token" contains "token" → redacted
    data = {"refresh_token": "rt_abc", "safe": "ok"}
    result = _redact_sensitive(data)
    assert result["refresh_token"] == "***"
    assert result["safe"] == "ok"


def test_redact_does_not_mutate_original():
    original = {"access_token": "abc", "query": "hello"}
    _ = _redact_sensitive(original)
    assert original["access_token"] == "abc"


# ---------------------------------------------------------------------------
# purge_old_logs
# ---------------------------------------------------------------------------

def test_purge_deletes_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.trace.logger.LOG_DIR", tmp_path)
    old = tmp_path / "app-2020-01-01.jsonl"
    new = tmp_path / "app-2099-01-01.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    old_mtime = time.time() - (15 * 86400)  # 15 days old
    import os
    os.utime(old, (old_mtime, old_mtime))

    from app.trace.logger import purge_old_logs
    deleted = purge_old_logs(retention_days=14)
    assert deleted == 1
    assert not old.exists()
    assert new.exists()


def test_purge_keeps_recent_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.trace.logger.LOG_DIR", tmp_path)
    recent = tmp_path / "app-2099-01-01.jsonl"
    recent.write_text("{}\n")

    from app.trace.logger import purge_old_logs
    deleted = purge_old_logs(retention_days=14)
    assert deleted == 0
    assert recent.exists()


def test_purge_returns_zero_on_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.trace.logger.LOG_DIR", tmp_path)
    from app.trace.logger import purge_old_logs
    assert purge_old_logs() == 0
