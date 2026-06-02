from __future__ import annotations

import os

from app.core.runtime_config import RuntimeConfig

_OLLAMA_PROVIDERS = frozenset({"ollama", "local"})


def resolve_local_provider_model(runtime_config: RuntimeConfig) -> str | None:
    """Return SITY_OLLAMA_MODEL if local Ollama is enabled and configured.

    Returns None when:
    - local_ai_enabled is False
    - local_ai_provider is not "ollama" / "local"
    - SITY_OLLAMA_MODEL env var is missing or empty

    Callers that get None while local_ai_enabled is True should log
    local_ai_misconfigured and leave local_provider=None so run_local_chat
    returns a controlled provider_not_configured error.
    """
    if not runtime_config.local_ai_enabled:
        return None
    if runtime_config.local_ai_provider.lower() not in _OLLAMA_PROVIDERS:
        return None
    model = os.getenv("SITY_OLLAMA_MODEL", "").strip()
    return model if model else None
