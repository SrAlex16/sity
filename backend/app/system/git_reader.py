from pathlib import Path
from typing import Any

from app.system.system_reader import load_system_access_config, run_read_command


def get_allowed_repositories() -> list[str]:
    config = load_system_access_config()
    return (
        config.get("git_access", {})
        .get("read", {})
        .get("allowed_repositories", [])
    )


def is_allowed_repository(repo_path: str) -> bool:
    resolved = Path(repo_path).expanduser().resolve()

    for allowed in get_allowed_repositories():
        allowed_resolved = Path(allowed).expanduser().resolve()
        if resolved == allowed_resolved:
            return True

    return False


def resolve_repository_path(repo_path: str | None) -> str:
    config = load_system_access_config()
    read_config = config.get("git_access", {}).get("read", {})

    if not repo_path:
        return str(read_config.get("default_repository", ""))

    aliases = read_config.get("repository_aliases", {})
    if repo_path in aliases:
        return str(aliases[repo_path])

    if repo_path.lower() == "sity":
        return str(read_config.get("default_repository", ""))

    return repo_path


def run_git(repo_path: str, args: list[str]) -> dict[str, Any]:
    repo_path = resolve_repository_path(repo_path)

    if not is_allowed_repository(repo_path):
        return {
            "ok": False,
            "message": "Repository is not allowed.",
            "repo_path": repo_path,
            "stdout": "",
            "stderr": "",
        }

    command = ["git", "-C", repo_path, *args]
    return run_read_command(command, timeout_seconds=8)


def git_status(repo_path: str) -> dict[str, Any]:
    result = run_git(repo_path, ["status", "--short", "--branch"])
    return {
        "repo_path": repo_path,
        "ok": result["ok"],
        "status": result["stdout"],
        "stderr": result["stderr"],
    }


def git_log(repo_path: str, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    result = run_git(
        repo_path,
        ["log", f"-{limit}", "--oneline", "--decorate"],
    )
    return {
        "repo_path": repo_path,
        "ok": result["ok"],
        "log": result["stdout"],
        "stderr": result["stderr"],
    }


def git_branches(repo_path: str) -> dict[str, Any]:
    result = run_git(repo_path, ["branch", "-a"])
    return {
        "repo_path": repo_path,
        "ok": result["ok"],
        "branches": result["stdout"],
        "stderr": result["stderr"],
    }


def git_remotes(repo_path: str) -> dict[str, Any]:
    result = run_git(repo_path, ["remote", "-v"])
    return {
        "repo_path": repo_path,
        "ok": result["ok"],
        "remotes": result["stdout"],
        "stderr": result["stderr"],
    }


def git_recent_diff(repo_path: str) -> dict[str, Any]:
    result = run_git(repo_path, ["diff", "--stat"])
    return {
        "repo_path": repo_path,
        "ok": result["ok"],
        "diff_stat": result["stdout"],
        "stderr": result["stderr"],
    }
