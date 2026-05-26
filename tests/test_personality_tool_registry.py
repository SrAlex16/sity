from __future__ import annotations

import pytest
from sqlmodel import Session

from app.core.tool_executor import ToolExecutor
from app.memory.db import engine
from app.tools.registry import ToolContext, dispatch_tool, has_handler


def test_update_personality_settings_registered() -> None:
    assert has_handler("update_personality_settings"), (
        "update_personality_settings is not registered"
    )


def test_update_personality_settings_dispatch(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

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
