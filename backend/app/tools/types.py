from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolExecutionResult:
    tool_name: str
    ok: bool
    message: str
    updated_parameters: list[str]
    raw_result: dict[str, Any]
