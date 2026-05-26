from __future__ import annotations

from app.cortex.providers.base import AITextProvider

_KNOWN_PROVIDERS = ("anthropic", "mock", "ollama", "local")


def build_ai_provider(provider_name: str, *, model: str) -> AITextProvider:
    """Instantiate and return an AITextProvider for *provider_name*.

    Args:
        provider_name: one of "anthropic", "mock", "ollama", "local"
            (matched case-insensitively).
        model: model identifier forwarded to the provider.

    Raises:
        ValueError: if *provider_name* is not in the known provider list.
            Previously AIGateway had an ``else`` branch that silently fell
            back to ClaudeProvider for any unrecognised name. This factory
            makes the error explicit so misconfiguration is caught early.
    """
    name = provider_name.strip().lower()

    if name == "mock":
        from app.cortex.mock_provider import MockProvider
        return MockProvider(model=model)

    if name == "anthropic":
        from app.cortex.claude_provider import ClaudeProvider
        return ClaudeProvider(model=model)

    if name in ("ollama", "local"):
        from app.cortex.ollama_provider import OllamaProvider
        return OllamaProvider(model=model)

    raise ValueError(
        f"Unknown AI provider {provider_name!r}. "
        f"Known providers: {', '.join(_KNOWN_PROVIDERS)}. "
        "To add a new provider implement AITextProvider and register it here."
    )
