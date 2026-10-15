from __future__ import annotations

import re
import subprocess
from typing import Any, Literal

from app.core.runtime_config import get_runtime_config

_MAX_STDOUT_CHARS = 4000
_MAX_STDERR_CHARS = 2000

_READ_COMMANDS = frozenset({
    "ls", "cat", "grep", "find", "which", "echo", "pwd", "whoami",
    "ps", "df", "du", "head", "tail", "wc", "stat", "file", "env", "printenv",
})

_GIT_READ_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "branch", "remote",
})

_ALWAYS_BLOCKED = frozenset({"reboot", "shutdown", "halt"})

_CURL_WRITE_METHOD_RE = re.compile(
    r"(?:-X|--request)\s+(POST|PUT|DELETE|PATCH)\b",
    re.IGNORECASE,
)
_CURL_DATA_RE = re.compile(r"(?:--data(?:-raw|-urlencode|-binary)?|-d)\b")


def classify_command(command: str) -> Literal["read", "write", "blocked"]:
    tokens = command.strip().split()
    if not tokens:
        return "write"
    first = tokens[0]

    # sudo reboot / shutdown / halt — always blocked regardless of yolo_mode
    if first == "sudo" and len(tokens) >= 2 and tokens[1] in _ALWAYS_BLOCKED:
        return "blocked"

    # git: read only for safe introspection subcommands
    if first == "git":
        if len(tokens) >= 2:
            sub = tokens[1]
            if sub in _GIT_READ_SUBCOMMANDS:
                return "read"
            if sub == "fetch" and "--dry-run" in tokens:
                return "read"
        return "write"

    # curl: read unless it sends a body or uses a mutating method
    if first == "curl":
        if _CURL_WRITE_METHOD_RE.search(command):
            return "write"
        if _CURL_DATA_RE.search(command):
            return "write"
        return "read"

    # python3/python -c and node -e run an inline expression — treat as read
    if first in ("python3", "python") and len(tokens) >= 2 and tokens[1] == "-c":
        return "read"
    if first == "node" and len(tokens) >= 2 and tokens[1] == "-e":
        return "read"

    if first in _READ_COMMANDS:
        return "read"

    return "write"


def execute_shell_action(payload: dict[str, Any]) -> dict[str, Any]:
    command = str(payload.get("command", "")).strip()
    working_dir = str(payload.get("working_dir", "."))
    timeout = int(payload.get("timeout", 30))

    if not command:
        return {"ok": False, "error": "Comando vacío."}

    project_root = get_runtime_config().project_root
    cwd = project_root if working_dir == "." else (project_root / working_dir).resolve()

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        truncated = len(stdout) > _MAX_STDOUT_CHARS
        return {
            "ok": True,
            "command": command,
            "returncode": proc.returncode,
            "stdout": stdout[:_MAX_STDOUT_CHARS],
            "stderr": stderr[:_MAX_STDERR_CHARS],
            "truncated": truncated,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Timeout: el comando superó los {timeout}s.",
            "command": command,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error ejecutando comando: {exc}",
            "command": command,
        }
