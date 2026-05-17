import json
from typing import Any

from app.system.git_reader import run_git


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "stdout": "", "stderr": message, "command": []}


def execute_git_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    repo_path = str(payload.get("repo_path", "sity"))

    if action == "fetch":
        return run_git(repo_path, ["fetch", "--all", "--prune"])

    if action == "pull_ff_only":
        remote = str(payload.get("remote", "origin"))
        branch = str(payload.get("branch", "main"))
        return run_git(repo_path, ["pull", "--ff-only", remote, branch])

    if action == "push":
        remote = str(payload.get("remote", "origin"))
        branch = str(payload.get("branch", "main"))
        return run_git(repo_path, ["push", remote, branch])

    if action == "create_branch":
        branch = str(payload.get("branch", "")).strip()
        if not branch:
            return _error("Missing branch name.")
        return run_git(repo_path, ["checkout", "-b", branch])

    if action == "checkout_branch":
        branch = str(payload.get("branch", "")).strip()
        if not branch:
            return _error("Missing branch name.")
        return run_git(repo_path, ["checkout", branch])

    if action == "commit":
        commit_message = str(payload.get("commit_message", "")).strip()
        if not commit_message:
            return _error("Missing commit message.")

        files: list[str] = payload.get("files") or []
        if files:
            add_args = ["add", "--"] + [str(f) for f in files]
        else:
            add_args = ["add", "-A"]

        add_result = run_git(repo_path, add_args)
        if not add_result.get("ok"):
            return add_result

        commit_result = run_git(repo_path, ["commit", "-m", commit_message])
        commit_result["pre_command"] = add_result.get("command", [])
        commit_result["pre_stdout"] = add_result.get("stdout", "")
        commit_result["pre_stderr"] = add_result.get("stderr", "")
        return commit_result

    return _error(f"Unsupported git action: {action}")


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)
