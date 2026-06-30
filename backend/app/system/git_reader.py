from pathlib import Path
from typing import Any

from app.system.system_reader import (
    _resolve_config_path,
    load_system_access_config,
    run_read_command,
)


def get_allowed_repositories() -> list[Path]:
    """Return allowed repository paths resolved to absolute Paths."""
    config = load_system_access_config()
    raw = (
        config.get("git_access", {})
        .get("read", {})
        .get("allowed_repositories", [])
    )
    return [_resolve_config_path(str(p)) for p in raw]


def is_allowed_repository(repo_path: str) -> bool:
    resolved = Path(repo_path).expanduser().resolve()
    return resolved in get_allowed_repositories()


def resolve_repository_path(repo_path: str | None) -> str:
    """Resolve an alias / empty string to an absolute repository path."""
    config = load_system_access_config()
    read_config = config.get("git_access", {}).get("read", {})

    if not repo_path:
        default = str(read_config.get("default_repository", ""))
        return str(_resolve_config_path(default))

    aliases = read_config.get("repository_aliases", {})
    if repo_path in aliases:
        return str(_resolve_config_path(str(aliases[repo_path])))

    if repo_path.lower() == "sity":
        default = str(read_config.get("default_repository", ""))
        return str(_resolve_config_path(default))

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


def git_log(repo_path: str, limit: int = 10, hours_back: int | None = None) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    args = ["log", f"-{limit}", "--pretty=format:%h  %ad  %s", "--date=short"]
    if hours_back is not None:
        hours_back = max(1, min(hours_back, 720))
        args.append(f"--since={hours_back} hours ago")
    result = run_git(repo_path, args)
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
