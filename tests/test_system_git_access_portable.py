"""Verify that system_access and git_access configs are portable.

These tests must pass regardless of where the project is checked out —
no hardcoded /home/alex/projects/sity anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.runtime_config import get_runtime_config
from app.system.system_reader import _resolve_config_path, is_allowed_path
from app.system.git_reader import (
    get_allowed_repositories,
    is_allowed_repository,
    resolve_repository_path,
)

_PROJECT_ROOT = get_runtime_config().project_root

# ---------------------------------------------------------------------------
# YAML source — no hardcoded personal paths
# ---------------------------------------------------------------------------

_YAML_SOURCE = (
    Path(__file__).resolve().parents[1] / "config" / "system_access.yaml"
).read_text(encoding="utf-8")


def test_yaml_has_no_hardcoded_project_path() -> None:
    assert "/home/alex/projects/sity" not in _YAML_SOURCE, (
        "config/system_access.yaml contains hardcoded /home/alex/projects/sity"
    )


# ---------------------------------------------------------------------------
# _resolve_config_path helper
# ---------------------------------------------------------------------------

def test_resolve_config_path_dot_returns_project_root() -> None:
    assert _resolve_config_path(".") == _PROJECT_ROOT.resolve()


def test_resolve_config_path_dot_dot_returns_parent() -> None:
    assert _resolve_config_path("..") == _PROJECT_ROOT.resolve().parent


def test_resolve_config_path_absolute_unchanged() -> None:
    assert _resolve_config_path("/tmp") == Path("/tmp")


def test_resolve_config_path_relative_anchored_to_project_root() -> None:
    result = _resolve_config_path("backend")
    assert result == (_PROJECT_ROOT / "backend").resolve()


# ---------------------------------------------------------------------------
# is_allowed_path — project root must be accepted
# ---------------------------------------------------------------------------

def test_is_allowed_path_accepts_project_root() -> None:
    assert is_allowed_path(_PROJECT_ROOT) is True


def test_is_allowed_path_accepts_subdirectory_of_project_root() -> None:
    assert is_allowed_path(_PROJECT_ROOT / "backend") is True


def test_is_allowed_path_accepts_parent_of_project_root() -> None:
    assert is_allowed_path(_PROJECT_ROOT.parent) is True


def test_is_allowed_path_rejects_unrelated_path() -> None:
    assert is_allowed_path(Path("/etc")) is False


# ---------------------------------------------------------------------------
# git_reader — repository resolution
# ---------------------------------------------------------------------------

def test_get_allowed_repositories_contains_project_root() -> None:
    allowed = get_allowed_repositories()
    assert _PROJECT_ROOT.resolve() in allowed, (
        f"project_root={_PROJECT_ROOT!r} not in allowed repos: {allowed}"
    )


def test_is_allowed_repository_accepts_project_root() -> None:
    assert is_allowed_repository(str(_PROJECT_ROOT)) is True


def test_is_allowed_repository_rejects_random_path() -> None:
    assert is_allowed_repository("/tmp/some-other-repo") is False


def test_resolve_repository_path_empty_returns_project_root() -> None:
    result = resolve_repository_path(None)
    assert Path(result).resolve() == _PROJECT_ROOT.resolve()


def test_resolve_repository_path_sity_alias_returns_project_root() -> None:
    result = resolve_repository_path("sity")
    assert Path(result).resolve() == _PROJECT_ROOT.resolve()


def test_resolve_repository_path_sity_case_insensitive() -> None:
    result = resolve_repository_path("SITY")
    assert Path(result).resolve() == _PROJECT_ROOT.resolve()


def test_resolve_repository_path_passthrough_for_unknown() -> None:
    result = resolve_repository_path("/some/other/path")
    assert result == "/some/other/path"
