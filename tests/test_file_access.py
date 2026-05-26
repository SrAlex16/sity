from __future__ import annotations

from pathlib import Path

import pytest

from app.system_agent.file_access import (
    apply_text_patch,
    apply_unified_diff,
    list_directory,
    preview_text_patch,
    preview_unified_diff,
    read_file,
    split_unified_diff_by_file,
    write_file,
)
from app.system_agent.file_audit import find_latest_reversible_file_change

ROOT = Path(__file__).resolve().parents[1]
_CONFIG = ROOT / "config"

_WRITE_TEST = _CONFIG / "local-file-access-test.txt"
_PATCH_TEST = _CONFIG / "local-file-access-patch.txt"
_DIFF_TEST = _CONFIG / "local-file-access-diff.txt"
_MULTI_A = _CONFIG / "local-file-access-multi-a.txt"
_MULTI_B = _CONFIG / "local-file-access-multi-b.txt"
_ALL_TEST_FILES = [_WRITE_TEST, _PATCH_TEST, _DIFF_TEST, _MULTI_A, _MULTI_B]


@pytest.fixture(autouse=True)
def cleanup_test_files():
    for p in _ALL_TEST_FILES:
        p.unlink(missing_ok=True)
    yield
    for p in _ALL_TEST_FILES:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Read / list — allowed
# ---------------------------------------------------------------------------

def test_list_directory_allowed_config() -> None:
    result = list_directory(str(_CONFIG))
    assert result.get("ok"), result


def test_read_file_allows_readme() -> None:
    result = read_file(str(ROOT / "README.md"))
    assert result.get("ok"), result


# ---------------------------------------------------------------------------
# Read / list — blocked outside repo
# ---------------------------------------------------------------------------

def test_list_directory_blocked_outside_repo() -> None:
    result = list_directory("/home/alex/Documents")
    assert not result.get("ok"), result


def test_read_file_blocked_outside_repo() -> None:
    result = read_file("/etc/passwd")
    assert not result.get("ok"), result


# ---------------------------------------------------------------------------
# Blocked sensitive paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", [
    ".git/config",
    ".env",
    ".env.local",
    "backend/.env",
    "backend/.env.local",
    "frontend/.env",
    "frontend/.env.local",
])
def test_read_file_blocks_sensitive_path(rel_path: str) -> None:
    result = read_file(str(ROOT / rel_path))
    assert not result.get("ok"), f"read_file should have blocked {rel_path}"


# ---------------------------------------------------------------------------
# write_file — allowed
# ---------------------------------------------------------------------------

def test_write_file_allowed_in_config() -> None:
    result = write_file(
        str(_WRITE_TEST), "hola local",
        pending_action_id="local_test_write", trace_id="local_trace",
    )
    assert result.get("ok"), result
    assert _WRITE_TEST.read_text(encoding="utf-8") == "hola local"


# ---------------------------------------------------------------------------
# write_file — blocked
# ---------------------------------------------------------------------------

def test_write_file_blocked_outside_repo() -> None:
    result = write_file(
        "/home/alex/Documents/local-file-access-test.txt", "hola",
        pending_action_id="local_test_blocked", trace_id="local_trace",
    )
    assert not result.get("ok"), result


def test_write_file_blocks_dot_env() -> None:
    result = write_file(
        str(ROOT / ".env"), "NOPE=1",
        pending_action_id="local_test_env", trace_id="local_trace",
    )
    assert not result.get("ok"), result


# ---------------------------------------------------------------------------
# Text patch
# ---------------------------------------------------------------------------

def test_preview_text_patch_allowed() -> None:
    _PATCH_TEST.write_text("alfa\nbeta\ngamma\n", encoding="utf-8")
    result = preview_text_patch(str(_PATCH_TEST), "beta", "beta mod")
    assert result.get("ok"), result


def test_apply_text_patch_modifies_content() -> None:
    _PATCH_TEST.write_text("alfa\nbeta\ngamma\n", encoding="utf-8")
    result = apply_text_patch(
        str(_PATCH_TEST), "beta", "beta mod",
        pending_action_id="local_test_patch", trace_id="local_trace",
    )
    assert result.get("ok"), result
    assert "beta mod" in _PATCH_TEST.read_text(encoding="utf-8")


def test_preview_text_patch_blocks_dot_env() -> None:
    result = preview_text_patch(str(ROOT / ".env"), "A", "B")
    assert not result.get("ok"), result


# ---------------------------------------------------------------------------
# Unified diff
# ---------------------------------------------------------------------------

_UNIFIED_DIFF = (
    "--- config/local-file-access-diff.txt\n"
    "+++ config/local-file-access-diff.txt\n"
    "@@ -1,3 +1,4 @@\n"
    " linea uno\n"
    "-linea dos\n"
    "+linea dos modificada\n"
    " linea tres\n"
    "+linea cuatro\n"
)


def test_preview_unified_diff_allowed() -> None:
    _DIFF_TEST.write_text("linea uno\nlinea dos\nlinea tres\n", encoding="utf-8")
    result = preview_unified_diff(_UNIFIED_DIFF)
    assert result.get("ok"), result


def test_apply_unified_diff_modifies_content() -> None:
    _DIFF_TEST.write_text("linea uno\nlinea dos\nlinea tres\n", encoding="utf-8")
    result = apply_unified_diff(
        _UNIFIED_DIFF,
        pending_action_id="local_test_unified", trace_id="local_trace",
    )
    assert result.get("ok"), result
    assert "linea cuatro" in _DIFF_TEST.read_text(encoding="utf-8")


def test_preview_unified_diff_blocks_dot_env() -> None:
    blocked_diff = "--- .env\n+++ .env\n@@ -1 +1 @@\n-A=1\n+B=2\n"
    result = preview_unified_diff(blocked_diff)
    assert not result.get("ok"), result


# ---------------------------------------------------------------------------
# Multi-file split
# ---------------------------------------------------------------------------

_MULTI_DIFF = (
    "--- config/local-file-access-multi-a.txt\n"
    "+++ config/local-file-access-multi-a.txt\n"
    "@@ -1,3 +1,3 @@\n"
    " a uno\n"
    "-a dos\n"
    "+a dos modificado\n"
    " a tres\n"
    "--- config/local-file-access-multi-b.txt\n"
    "+++ config/local-file-access-multi-b.txt\n"
    "@@ -1,3 +1,4 @@\n"
    " b uno\n"
    " b dos\n"
    "-b tres\n"
    "+b tres modificado\n"
    "+b cuatro\n"
)

_BLOCKED_MULTI_DIFF = (
    "--- config/local-file-access-multi-a.txt\n"
    "+++ config/local-file-access-multi-a.txt\n"
    "@@ -1,3 +1,3 @@\n"
    " a uno\n"
    "-a dos\n"
    "+a dos otra vez\n"
    " a tres\n"
    "--- .env\n"
    "+++ .env\n"
    "@@ -1 +1 @@\n"
    "-A=1\n"
    "+B=2\n"
)


def test_split_unified_diff_by_file_count() -> None:
    _MULTI_A.write_text("a uno\na dos\na tres\n", encoding="utf-8")
    _MULTI_B.write_text("b uno\nb dos\nb tres\n", encoding="utf-8")
    result = split_unified_diff_by_file(_MULTI_DIFF)
    assert result.get("ok"), result
    assert result.get("count") == 2


def test_split_unified_diff_blocks_mixed_plan_with_sensitive_file() -> None:
    _MULTI_A.write_text("a uno\na dos\na tres\n", encoding="utf-8")
    result = split_unified_diff_by_file(_BLOCKED_MULTI_DIFF)
    assert not result.get("ok"), result
    assert result.get("rejected_entire_plan"), result


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_find_latest_reversible_file_change_returns_dict() -> None:
    result = find_latest_reversible_file_change()
    assert isinstance(result, dict)
