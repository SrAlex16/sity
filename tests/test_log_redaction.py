"""Tests for app.trace.redaction.redact_tool_call_input.

Verifies that:
- Always-redact tools never expose content in preview.
- Large inputs are truncated and marked redacted.
- Small inputs are included in full with redacted=False.
- All input types (str, list, None, unknown) are handled without error.
"""
from __future__ import annotations

import pytest

from app.trace.redaction import redact_tool_call_input


# ---------------------------------------------------------------------------
# Always-redact tools: no preview, redacted=True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", [
    "write_file",
    "apply_text_patch",
    "apply_unified_diff",
    "apply_multi_file_unified_diff_plan",
])
def test_always_redact_dict_has_no_preview(tool_name: str) -> None:
    result = redact_tool_call_input(tool_name, {"path": "x.py", "content": "secret"})
    assert result["redacted"] is True
    assert "preview" not in result


def test_write_file_exposes_keys_not_content() -> None:
    result = redact_tool_call_input("write_file", {"path": "x.py", "content": "a" * 1000})
    assert "content" in result["keys"]
    assert "preview" not in result
    assert result["length"] > 0


def test_always_redact_str_has_no_preview() -> None:
    result = redact_tool_call_input("apply_text_patch", "patch content here")
    assert result["redacted"] is True
    assert "preview" not in result


# ---------------------------------------------------------------------------
# Large dict input: truncated preview, redacted=True
# ---------------------------------------------------------------------------

def test_large_dict_preview_is_truncated() -> None:
    big_input = {"path": "x.py", "content": "x" * 1000}
    result = redact_tool_call_input("read_file", big_input, max_chars=300)
    assert result["redacted"] is True
    assert "preview" in result
    assert len(result["preview"]) <= 300


def test_large_dict_full_content_not_in_preview() -> None:
    big_input = {"content": "sensitive " * 100}
    result = redact_tool_call_input("some_tool", big_input, max_chars=50)
    assert len(result["preview"]) <= 50


# ---------------------------------------------------------------------------
# Small/innocuous input: full preview, redacted=False
# ---------------------------------------------------------------------------

def test_small_dict_not_redacted() -> None:
    result = redact_tool_call_input("read_file", {"path": "app/main.py"}, max_chars=300)
    assert result["redacted"] is False
    assert "preview" in result
    assert "app/main.py" in result["preview"]


def test_small_dict_keys_listed() -> None:
    result = redact_tool_call_input("read_file", {"path": "x.py", "start": 1})
    assert "keys" in result
    assert set(result["keys"]) == {"path", "start"}


def test_small_dict_length_reflects_serialized_size() -> None:
    inp = {"path": "x.py"}
    result = redact_tool_call_input("read_file", inp)
    assert result["length"] > 0


# ---------------------------------------------------------------------------
# str input
# ---------------------------------------------------------------------------

def test_short_str_not_redacted() -> None:
    result = redact_tool_call_input("some_tool", "hello", max_chars=300)
    assert result["type"] == "str"
    assert result["redacted"] is False
    assert result["preview"] == "hello"


def test_long_str_truncated() -> None:
    result = redact_tool_call_input("some_tool", "x" * 500, max_chars=100)
    assert result["redacted"] is True
    assert len(result["preview"]) == 100


# ---------------------------------------------------------------------------
# list input
# ---------------------------------------------------------------------------

def test_list_input_returns_type_and_length() -> None:
    result = redact_tool_call_input("some_tool", [1, 2, 3])
    assert result["type"] == "list"
    assert result["length"] == 3
    assert result["redacted"] is False


def test_list_always_redact_tool() -> None:
    result = redact_tool_call_input("write_file", ["a", "b"])
    assert result["redacted"] is True


# ---------------------------------------------------------------------------
# None input
# ---------------------------------------------------------------------------

def test_none_input_returns_type_none() -> None:
    result = redact_tool_call_input("any_tool", None)
    assert result["type"] == "none"
    assert result["redacted"] is False


# ---------------------------------------------------------------------------
# Unknown scalar type — does not raise
# ---------------------------------------------------------------------------

def test_unknown_type_does_not_raise() -> None:
    result = redact_tool_call_input("any_tool", 42)
    assert isinstance(result, dict)
    assert "type" in result
    assert "redacted" in result
