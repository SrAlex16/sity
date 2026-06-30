"""Tests for git_log() with hours_back parameter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.system.git_reader import git_log


def _fake_run_git_ok(repo_path: str, args: list[str]):
    return {"ok": True, "stdout": "abc1234  2026-06-30  feat: algo", "stderr": ""}


def _fake_run_git_empty(repo_path: str, args: list[str]):
    return {"ok": True, "stdout": "", "stderr": ""}


def _fake_run_git_error(repo_path: str, args: list[str]):
    return {"ok": False, "stdout": "", "stderr": "fatal: not a git repository"}


# ── hours_back passed to git args ─────────────────────────────────────────────

def test_hours_back_adds_since_flag() -> None:
    captured: list[list[str]] = []

    def capture_run(repo_path: str, args: list[str]):
        captured.append(args)
        return _fake_run_git_ok(repo_path, args)

    with patch("app.system.git_reader.run_git", side_effect=capture_run):
        git_log("", hours_back=24)

    assert any("--since=24 hours ago" in a for a in captured[0])


def test_no_hours_back_omits_since_flag() -> None:
    captured: list[list[str]] = []

    def capture_run(repo_path: str, args: list[str]):
        captured.append(args)
        return _fake_run_git_ok(repo_path, args)

    with patch("app.system.git_reader.run_git", side_effect=capture_run):
        git_log("")

    assert not any("--since" in a for a in captured[0])


# ── return values ──────────────────────────────────────────────────────────────

def test_returns_log_when_commits_exist() -> None:
    with patch("app.system.git_reader.run_git", side_effect=_fake_run_git_ok):
        result = git_log("", hours_back=24)
    assert result["ok"] is True
    assert "abc1234" in result["log"]


def test_returns_empty_log_when_no_commits_in_range() -> None:
    with patch("app.system.git_reader.run_git", side_effect=_fake_run_git_empty):
        result = git_log("", hours_back=1)
    assert result["ok"] is True
    assert result["log"] == ""


def test_returns_ok_false_on_git_error() -> None:
    with patch("app.system.git_reader.run_git", side_effect=_fake_run_git_error):
        result = git_log("")
    assert result["ok"] is False
    assert result["log"] == ""


# ── hours_back clamping ────────────────────────────────────────────────────────

def test_hours_back_clamped_to_max_720() -> None:
    captured: list[list[str]] = []

    def capture_run(repo_path: str, args: list[str]):
        captured.append(args)
        return _fake_run_git_ok(repo_path, args)

    with patch("app.system.git_reader.run_git", side_effect=capture_run):
        git_log("", hours_back=9999)

    assert "--since=720 hours ago" in captured[0]


def test_hours_back_clamped_to_min_1() -> None:
    captured: list[list[str]] = []

    def capture_run(repo_path: str, args: list[str]):
        captured.append(args)
        return _fake_run_git_ok(repo_path, args)

    with patch("app.system.git_reader.run_git", side_effect=capture_run):
        git_log("", hours_back=0)

    assert "--since=1 hours ago" in captured[0]
