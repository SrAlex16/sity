"""Tests for app.actions.git_actions.

Strategy: mock run_git at the import site so no real git subprocess is spawned.
Focus: all validation-error branches (missing branch, missing commit message,
failed add step) and each happy path, plus the parse_payload helper.
"""
from __future__ import annotations

import json
from unittest.mock import call, patch

import pytest

from app.actions.git_actions import execute_git_action, parse_payload


_OK = {"ok": True, "stdout": "", "stderr": "", "command": []}
_FAIL = {"ok": False, "stdout": "", "stderr": "error", "command": []}


def _run(payload: dict):
    return execute_git_action(payload)


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

class TestFetch:
    def test_fetch_calls_run_git(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            result = _run({"action": "fetch", "repo_path": "myrepo"})
        mock.assert_called_once_with("myrepo", ["fetch", "--all", "--prune"])
        assert result["ok"] is True

    def test_fetch_default_repo_path(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "fetch"})
        mock.assert_called_once_with("sity", ["fetch", "--all", "--prune"])


# ---------------------------------------------------------------------------
# pull_ff_only
# ---------------------------------------------------------------------------

class TestPullFfOnly:
    def test_pull_default_remote_branch(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "pull_ff_only"})
        mock.assert_called_once_with("sity", ["pull", "--ff-only", "origin", "main"])

    def test_pull_custom_remote_branch(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "pull_ff_only", "remote": "upstream", "branch": "dev"})
        mock.assert_called_once_with("sity", ["pull", "--ff-only", "upstream", "dev"])

    def test_pull_failure_propagated(self):
        with patch("app.actions.git_actions.run_git", return_value=_FAIL):
            result = _run({"action": "pull_ff_only"})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------

class TestPush:
    def test_push_default_remote_branch(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "push"})
        mock.assert_called_once_with("sity", ["push", "origin", "main"])

    def test_push_custom_remote_branch(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "push", "remote": "upstream", "branch": "release"})
        mock.assert_called_once_with("sity", ["push", "upstream", "release"])


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------

class TestCreateBranch:
    def test_missing_branch_returns_error(self):
        result = _run({"action": "create_branch", "branch": ""})
        assert result["ok"] is False
        assert "Missing branch name" in result["stderr"]

    def test_missing_branch_key_returns_error(self):
        result = _run({"action": "create_branch"})
        assert result["ok"] is False

    def test_create_branch_success(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "create_branch", "branch": "feature/x"})
        mock.assert_called_once_with("sity", ["checkout", "-b", "feature/x"])

    def test_create_branch_whitespace_stripped(self):
        result = _run({"action": "create_branch", "branch": "   "})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# checkout_branch
# ---------------------------------------------------------------------------

class TestCheckoutBranch:
    def test_missing_branch_returns_error(self):
        result = _run({"action": "checkout_branch", "branch": ""})
        assert result["ok"] is False
        assert "Missing branch name" in result["stderr"]

    def test_checkout_success(self):
        with patch("app.actions.git_actions.run_git", return_value=_OK) as mock:
            _run({"action": "checkout_branch", "branch": "main"})
        mock.assert_called_once_with("sity", ["checkout", "main"])


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

class TestCommit:
    def test_missing_commit_message_returns_error(self):
        result = _run({"action": "commit", "commit_message": ""})
        assert result["ok"] is False
        assert "Missing commit message" in result["stderr"]

    def test_missing_commit_message_key_returns_error(self):
        result = _run({"action": "commit"})
        assert result["ok"] is False

    def test_commit_with_specific_files(self):
        add_ok = {"ok": True, "stdout": "", "stderr": "", "command": ["git", "add"]}
        commit_ok = {"ok": True, "stdout": "1 file changed", "stderr": "", "command": ["git", "commit"]}
        with patch("app.actions.git_actions.run_git", side_effect=[add_ok, commit_ok]) as mock:
            result = _run({"action": "commit", "commit_message": "fix: thing", "files": ["src/foo.py"]})
        assert mock.call_count == 2
        assert mock.call_args_list[0] == call("sity", ["add", "--", "src/foo.py"])
        assert mock.call_args_list[1] == call("sity", ["commit", "-m", "fix: thing"])
        assert result["ok"] is True
        assert result["pre_command"] == ["git", "add"]
        assert result["pre_stdout"] == ""

    def test_commit_without_files_uses_add_all(self):
        add_ok = {"ok": True, "stdout": "", "stderr": "", "command": []}
        commit_ok = {"ok": True, "stdout": "", "stderr": "", "command": []}
        with patch("app.actions.git_actions.run_git", side_effect=[add_ok, commit_ok]) as mock:
            _run({"action": "commit", "commit_message": "chore: update", "files": []})
        assert mock.call_args_list[0] == call("sity", ["add", "-A"])

    def test_commit_with_none_files_uses_add_all(self):
        add_ok = {"ok": True, "stdout": "", "stderr": "", "command": []}
        commit_ok = {"ok": True, "stdout": "", "stderr": "", "command": []}
        with patch("app.actions.git_actions.run_git", side_effect=[add_ok, commit_ok]) as mock:
            _run({"action": "commit", "commit_message": "chore: update"})
        assert mock.call_args_list[0] == call("sity", ["add", "-A"])

    def test_add_failure_short_circuits(self):
        add_fail = {"ok": False, "stdout": "", "stderr": "lock error", "command": []}
        with patch("app.actions.git_actions.run_git", return_value=add_fail) as mock:
            result = _run({"action": "commit", "commit_message": "wip"})
        assert result["ok"] is False
        assert result["stderr"] == "lock error"
        assert mock.call_count == 1  # commit step never reached

    def test_commit_propagates_pre_stderr(self):
        add_ok = {"ok": True, "stdout": "staged", "stderr": "warn", "command": ["git", "add"]}
        commit_ok = {"ok": True, "stdout": "done", "stderr": "", "command": ["git", "commit"]}
        with patch("app.actions.git_actions.run_git", side_effect=[add_ok, commit_ok]):
            result = _run({"action": "commit", "commit_message": "msg", "files": ["a.py"]})
        assert result["pre_stderr"] == "warn"
        assert result["pre_stdout"] == "staged"


# ---------------------------------------------------------------------------
# unsupported action
# ---------------------------------------------------------------------------

class TestUnsupportedAction:
    def test_unknown_action_returns_error(self):
        result = _run({"action": "rebase"})
        assert result["ok"] is False
        assert "rebase" in result["stderr"]

    def test_none_action_returns_error(self):
        result = _run({})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# parse_payload
# ---------------------------------------------------------------------------

class TestParsePayload:
    def test_valid_json(self):
        data = {"action": "fetch", "repo_path": "sity"}
        assert parse_payload(json.dumps(data)) == data

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_payload("not-json{")
