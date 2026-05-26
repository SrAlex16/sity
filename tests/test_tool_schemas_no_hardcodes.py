"""Verify that tool_schemas.py contains no hardcoded personal paths.

Two guarantees:
1. The source file does not contain '/home/alex/projects/sity'.
2. The rendered descriptions include the runtime project_root
   (confirming _PROJECT_ROOT is wired up, not an empty string).
"""
from __future__ import annotations

from pathlib import Path

from app.core.runtime_config import get_runtime_config
from app.cortex import tool_schemas

_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "backend" / "app" / "cortex" / "tool_schemas.py"
).read_text(encoding="utf-8")

_PROJECT_ROOT = str(get_runtime_config().project_root)


def test_tool_schemas_source_has_no_hardcoded_path() -> None:
    assert "/home/alex/projects/sity" not in _SOURCE, (
        "tool_schemas.py contains a hardcoded personal path — use _PROJECT_ROOT"
    )


def test_git_repo_path_field_contains_project_root() -> None:
    desc = tool_schemas._GIT_REPO_PATH_FIELD["description"]
    assert _PROJECT_ROOT in desc, (
        f"_GIT_REPO_PATH_FIELD description does not contain project_root={_PROJECT_ROOT!r}"
    )


def test_git_propose_action_repo_path_contains_project_root() -> None:
    props = tool_schemas.GIT_PROPOSE_ACTION_TOOL["input_schema"]["properties"]
    desc = props["repo_path"]["description"]
    assert _PROJECT_ROOT in desc, (
        f"GIT_PROPOSE_ACTION_TOOL repo_path description does not contain project_root={_PROJECT_ROOT!r}"
    )


def test_project_root_is_non_empty() -> None:
    """Guard: _PROJECT_ROOT must resolve to something meaningful."""
    assert _PROJECT_ROOT, "_PROJECT_ROOT is empty — check get_runtime_config()"
    assert _PROJECT_ROOT != ".", "_PROJECT_ROOT resolved to '.' — SITY_PROJECT_ROOT may be unset"
