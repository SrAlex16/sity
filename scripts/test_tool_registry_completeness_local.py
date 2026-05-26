#!/usr/bin/env python3
"""Wrapper — delegates to pytest. Kept for manual/compatibility use.

Run all local tests:
    backend/.venv/bin/python -m pytest -q tests/

Run this module only:
    backend/.venv/bin/python -m pytest -q tests/test_tool_registry_completeness.py
"""
import pytest
raise SystemExit(pytest.main(["-q", "tests/test_tool_registry_completeness.py"]))
