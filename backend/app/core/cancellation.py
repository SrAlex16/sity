from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class RunningOperation:
    cancelled: bool = False
    process: subprocess.Popen | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_lock = Lock()
_operations: dict[str, RunningOperation] = {}


def register_operation(client_turn_id: str) -> RunningOperation:
    with _lock:
        operation = RunningOperation()
        _operations[client_turn_id] = operation
        return operation


def get_operation(client_turn_id: str) -> RunningOperation | None:
    with _lock:
        return _operations.get(client_turn_id)


def set_process(client_turn_id: str, process: subprocess.Popen) -> None:
    with _lock:
        operation = _operations.get(client_turn_id)
        if operation:
            operation.process = process


def cancel_operation(client_turn_id: str) -> bool:
    with _lock:
        operation = _operations.get(client_turn_id)
        if not operation:
            return False

        operation.cancelled = True

        if operation.process and operation.process.poll() is None:
            operation.process.terminate()

        return True


def is_cancelled(client_turn_id: str | None) -> bool:
    if not client_turn_id:
        return False
    with _lock:
        op = _operations.get(client_turn_id)
        return bool(op and op.cancelled)


def clear_operation(client_turn_id: str) -> None:
    with _lock:
        _operations.pop(client_turn_id, None)
