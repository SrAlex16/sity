"""
Single source of truth for allowed systemd services.

Reads from system_access.safe_actions.allowed_services in system_access.yaml.
Cached per process — the YAML does not change at runtime.

Separate from system_access.read.allowed_services, which governs which
services the read-status handler can inspect (a wider, read-only list).
"""

from __future__ import annotations

import functools

from app.system.system_reader import load_system_access_config


@functools.cache
def get_allowed_systemd_services() -> tuple[str, ...]:
    """
    Services allowed for start/stop/restart via safe_actions policy.

    Source: system_access.safe_actions.allowed_services in system_access.yaml.
    Returns an empty tuple if the config is missing or the section is absent.
    """
    config = load_system_access_config()
    return tuple(
        config.get("system_access", {})
        .get("safe_actions", {})
        .get("allowed_services", [])
    )
