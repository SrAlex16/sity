import json
from typing import Any

from app.system.git_reader import run_git


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
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Missing branch name.",
                "command": [],
            }
        return run_git(repo_path, ["checkout", "-b", branch])

    return {
        "ok": False,
        "stdout": "",
        "stderr": f"Unsupported git action: {action}",
        "command": [],
    }


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)
