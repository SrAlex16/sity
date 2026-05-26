#!/usr/bin/env python3
"""Wrapper — delegates to pytest. Kept for manual/compatibility use.

Run all local tests:
    backend/.venv/bin/python -m pytest -q tests/

Run this module only:
    backend/.venv/bin/python -m pytest -q tests/test_apply_multi_file_unified_diff_plan_tool_registry.py
"""
import pytest
raise SystemExit(pytest.main(["-q", "tests/test_apply_multi_file_unified_diff_plan_tool_registry.py"]))
