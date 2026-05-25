from __future__ import annotations

import re

# Esto no debe crear acciones ni interpretar intención de negocio.
# Solo selecciona un toolset/contexto más pequeño usando señales técnicas conservadoras.
# La acción real debe venir siempre de una tool estructurada interpretada por Claude.

from app.cortex.tool_schemas import (
    BASE_TOOLSET,
    DEBUG_TOOLSET,
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET,
    PERSONALITY_TOOLSET,
    SENSES_TOOLSET,
    SERVICE_CONFIG_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET,
)

# ── Tool-name → toolset index ─────────────────────────────────────────────────
# Built once at import. When a tool name appears verbatim in the message, its
# toolset is added automatically — no parallel term list to maintain.
_TOOL_TO_TOOLSET: dict[str, list[dict]] = {}
for _toolset in [
    GIT_TOOLSET, SERVICE_CONFIG_TOOLSET, SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET, SENSES_TOOLSET, DEBUG_TOOLSET, PERSONALITY_TOOLSET,
]:
    for _tool in _toolset:
        _TOOL_TO_TOOLSET[_tool["name"]] = _toolset
del _toolset, _tool

# ── Compiled regex patterns (roots, not inflected forms) ──────────────────────
_GIT_RE = re.compile(
    r"\bgit\b|\bcommit\b|\bramas?\b|\bbranch(?:es)?\b"
    r"|\bpull\b|\bpush\b|\bfetch\b|\bcheckout\b|\bdiff\b"
    r"|\bestado\s+git\b|\bstatus\s+git\b",
    re.IGNORECASE,
)
_SERVICE_CONFIG_RE = re.compile(
    r"\badd_allowed\b|\bremove_allowed\b|\ballowlist\b"
    r"|\bservicios\s+permitidos\b|\blista\s+de\s+servicios\b"
    r"|\bservicios\s+que\s+puedes\b",
    re.IGNORECASE,
)
_SERVICE_CONTROL_RE = re.compile(
    r"\breinicia\b|\barranca\b|\bdetén\b|\bdetener\b|\bpara\s+el\b"
    r"|\bsystemctl\b|\bsity-(?:backend|frontend|test)\b"
    r"|\b(?:backend|frontend)\b",
    re.IGNORECASE,
)
_SYSTEM_RE = re.compile(
    r"\braspberry\b|\bsistema\b|\bcpu\b|\bram\b|\bmemoria\b"
    r"|\bdisco\b|\bespacio\b|\bprocesos\b|\bsystemd\b",
    re.IGNORECASE,
)
_SENSE_RE = re.compile(
    r"\bfoto\b|\bcámar|\bcamar|\bwebcam\b"
    r"|\bmicr(?:ó|o)fono\b|\bmicro\b|\baudio\b"
    r"|\bcaptur|\bgraba",
    re.IGNORECASE,
)
_DEBUG_RE = re.compile(
    r"\bdebug\b|\btraza\b|\btrace\b|\blogs\b|\beventos\b"
    r"|\berrores\b|\bherramientas\b",
    re.IGNORECASE,
)
_PERSONALITY_FIELD_RE = re.compile(
    r"\bsarcasmo\b|\brudeza\b|\bcalidez\b|\bhonestidad\b|\bpaciencia\b"
    r"|\bmelancolía\b|\bmelancolia\b|\btsundere\b|\bverbosidad\b"
    r"|\bpersonalidad\b|\bmala\s+leche\b",
    re.IGNORECASE,
)
_PERSONALITY_ACTION_RE = re.compile(
    r"\bsube\b|\bbaja\b|\bajusta\b|\bcambia\b|\bpon\b|\bponte\b|\bslider\b",
    re.IGNORECASE,
)
# Union of all technical signals — used by the "is this purely conversational?" gate.
_IS_TECHNICAL_RE = re.compile(
    r"\bgit\b|\bcommit\b|\brama|\bbranch|\bpull\b|\bpush\b|\bfetch\b"
    r"|\bfoto\b|\bcámar|\bcamar|\bwebcam\b|\bcaptur|\bgraba|\baudio\b"
    r"|\bmicr(?:ó|o)fono\b|\bmicro\b"
    r"|\bdebug\b|\btraza\b|\btrace\b|\blogs\b"
    r"|\breinicia\b|\barranca\b|\bservicio\b|\bsystemd\b|\bbackend\b|\bfrontend\b"
    r"|\bcpu\b|\bram\b|\bdisco\b|\braspberry\b|\bsistema\b"
    r"|\bpersonalidad\b|\bsarcasmo\b|\bcalidez\b",
    re.IGNORECASE,
)


def _dedupe_tools(tools: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for tool in tools:
        name = tool.get("name", "")
        if name not in seen:
            seen.add(name)
            result.append(tool)
    return result


def message_mentions_file_path(message: str) -> bool:
    text = message.strip()
    return (
        "/" in text
        or "./" in text
        or "../" in text
        or "config/" in text
        or "backend/" in text
        or "frontend/" in text
        or "scripts/" in text
        or "README.md" in text
        or ".env" in text
    )


def _looks_like_conversation_only(message: str) -> bool:
    # A verbatim tool name in the message is always a technical signal.
    normalized = message.lower()
    if any(name in normalized for name in _TOOL_TO_TOOLSET):
        return False
    return not _IS_TECHNICAL_RE.search(message)


def history_limit_for_message(message: str) -> int:
    normalized = message.lower()

    context_heavy_terms = [
        "ayer", "antes", "recuerdas", "dijiste", "hablamos",
        "historial", "qué hicimos", "que hicimos", "resume",
    ]

    single_action_terms = [
        "añade", "agrega", "quita", "elimina",
        "reinicia", "arranca", "para el",
        "servicios permitidos", "allowlist",
        "saca una foto", "graba audio", "graba ",
    ]

    technical_terms = [
        "error", "bug", "trace", "debug", "logs", "falló", "fallo",
        "repo", "git", "servicio", "backend", "frontend",
        "raspberry", "sistema", "cpu", "ram", "disco",
    ]

    if any(term in normalized for term in single_action_terms):
        return 4

    if any(term in normalized for term in context_heavy_terms):
        return 8

    if any(term in normalized for term in technical_terms):
        return 8

    return 4


def select_toolset_for_message(message: str) -> list[dict]:
    if message_mentions_file_path(message):
        return list(FILE_AGENT_TOOLSET)

    if _looks_like_conversation_only(message):
        return list(BASE_TOOLSET)

    selected = list(BASE_TOOLSET)

    # Primary signal: tool name mentioned verbatim → add its toolset directly.
    normalized = message.lower()
    seen_toolset_ids: set[int] = set()
    for tool_name, toolset in _TOOL_TO_TOOLSET.items():
        if tool_name in normalized:
            tid = id(toolset)
            if tid not in seen_toolset_ids:
                seen_toolset_ids.add(tid)
                selected.extend(toolset)

    # Secondary signal: natural language roots via compiled regex.
    if _GIT_RE.search(message):
        selected.extend(GIT_TOOLSET)

    if _SERVICE_CONFIG_RE.search(message):
        selected.extend(SERVICE_CONFIG_TOOLSET)
    elif _SERVICE_CONTROL_RE.search(message):
        selected.extend(SERVICE_CONTROL_TOOLSET)
    elif _SYSTEM_RE.search(message):
        selected.extend(SYSTEM_TOOLSET)

    if _SENSE_RE.search(message):
        selected.extend(SENSES_TOOLSET)

    if _DEBUG_RE.search(message):
        selected.extend(DEBUG_TOOLSET)

    if _PERSONALITY_FIELD_RE.search(message) and _PERSONALITY_ACTION_RE.search(message):
        selected.extend(PERSONALITY_TOOLSET)

    return _dedupe_tools(selected)
