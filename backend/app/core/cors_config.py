"""cors_config.py — CORS origin resolution for Sity backend.

Environment variables (read on each call — no module-level caching):
  SITY_CORS_ORIGINS   Comma-separated list of allowed origins.
                      Takes precedence over the legacy singular var.
  SITY_CORS_ORIGIN    Legacy single-value origin (backward-compat).
                      Used only when SITY_CORS_ORIGINS is absent/empty.

Defaults always included:
  http://localhost:5173
  http://127.0.0.1:5173

Usage in main.py:
  from app.core.cors_config import get_cors_origins
  app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), ...)

Usage in .env for local development:
  SITY_CORS_ORIGINS=http://192.168.1.133:5174,http://192.168.1.133:5173

The default port 5173 covers the production Vite frontend.
Temporary dev ports (5174, etc.) should be added via SITY_CORS_ORIGINS.
"""

from __future__ import annotations

import os

_BUILTIN_DEFAULTS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def parse_cors_origins(
    raw: str,
    *,
    defaults: list[str] | None = None,
) -> list[str]:
    """Parse a comma-separated origins string and merge with defaults.

    Args:
        raw:      Comma-separated origin URLs (e.g. from an env var).
                  Empty string → no extra origins added.
        defaults: Origins that are always included. If None, uses the
                  built-in defaults (localhost:5173 / 127.0.0.1:5173).

    Returns:
        Deduplicated list — defaults first, then extra origins in order.
        Each token is stripped; empty tokens are discarded.
    """
    seen: set[str] = set()
    result: list[str] = []

    base = _BUILTIN_DEFAULTS if defaults is None else defaults
    for origin in base:
        o = origin.strip()
        if o and o not in seen:
            seen.add(o)
            result.append(o)

    for token in raw.split(","):
        o = token.strip()
        if o and o not in seen:
            seen.add(o)
            result.append(o)

    return result


def get_cors_origins() -> list[str]:
    """Return the list of allowed CORS origins based on env configuration.

    Reads SITY_CORS_ORIGINS (comma-separated, takes precedence) or falls
    back to SITY_CORS_ORIGIN (legacy single-value) when the plural var is
    absent or empty.  Built-in defaults (localhost:5173) are always included.
    """
    raw = os.getenv("SITY_CORS_ORIGINS", "").strip()
    if not raw:
        # Backward compat: support the legacy singular var.
        raw = os.getenv("SITY_CORS_ORIGIN", "").strip()
    return parse_cors_origins(raw)
