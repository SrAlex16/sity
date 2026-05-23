from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.core.tool_executor import ToolExecutionResult


@dataclass
class ToolContext:
    tool_name: str
    tool_input: dict[str, Any]
    trace_id: str
    executor: Any  # ToolExecutor — avoid circular import


_HANDLERS: dict[str, Callable[[ToolContext], ToolExecutionResult]] = {}


def tool_handler(name: str) -> Callable:
    def decorator(fn: Callable[[ToolContext], ToolExecutionResult]) -> Callable:
        _HANDLERS[name] = fn
        return fn
    return decorator


def has_handler(tool_name: str) -> bool:
    return tool_name in _HANDLERS


def dispatch_tool(ctx: ToolContext) -> ToolExecutionResult:
    return _HANDLERS[ctx.tool_name](ctx)
