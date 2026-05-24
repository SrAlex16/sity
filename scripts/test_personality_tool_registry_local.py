#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlmodel import Session  # noqa: E402

from app.core.tool_executor import ToolExecutor  # noqa: E402
from app.memory.db import engine, init_db  # noqa: E402
from app.tools.registry import ToolContext, dispatch_tool, has_handler  # noqa: E402


def main() -> None:
    init_db()

    with Session(engine) as session:
        executor = ToolExecutor(session)

        assert has_handler("update_personality_settings"), (
            "update_personality_settings is not registered"
        )

        ctx = ToolContext(
            tool_name="update_personality_settings",
            tool_input={
                "updates": [
                    {
                        "parameter": "verbosity_level",
                        "operation": "set_absolute",
                        "value": 0.5,
                    }
                ],
                "reason": "local registry test",
            },
            trace_id="trc_personality_registry_local_test",
            executor=executor,
        )

        result = dispatch_tool(ctx)

        assert result.ok is True, result
        assert "verbosity_level" in result.updated_parameters, result.updated_parameters
        assert result.raw_result.get("success") is True, result.raw_result

        print("personality tool registry local test ok")


if __name__ == "__main__":
    main()
