from __future__ import annotations

import re
from dataclasses import dataclass

# Esto no debe crear acciones ni interpretar intención de negocio.
# Solo selecciona un toolset/contexto más pequeño usando señales técnicas conservadoras.
# La acción real debe venir siempre de una tool estructurada interpretada por Claude.

from app.cortex.tool_schemas import (
    BASE_TOOLSET,
    DEBUG_TOOLSET,
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET,
    PENDING_ACTION_TOOLSET,
    PERSONALITY_TOOLSET,
    SENSES_TOOLSET,
    SERVICE_CONFIG_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET,
)

# ── Tool-name → toolset index ─────────────────────────────────────────────────
# Built once at import from the actual schema lists.
# No parallel term list to maintain: adding a tool to a schema is enough.
# FILE_AGENT_TOOLSET is included so that explicit tool names like "read_file"
# or "write_file" in the message activate the full file toolset structurally,
# without relying on BASE_TOOLSET having them by default.
_TOOL_TO_TOOLSET: dict[str, list[dict]] = {}
for _toolset in [
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET, SERVICE_CONFIG_TOOLSET, SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET, SENSES_TOOLSET, DEBUG_TOOLSET, PERSONALITY_TOOLSET,
    PENDING_ACTION_TOOLSET,
]:
    for _tool in _toolset:
        _TOOL_TO_TOOLSET[_tool["name"]] = _toolset
del _toolset, _tool

# ── Legacy NL keyword regexes ─────────────────────────────────────────────────
# Used only by _legacy_keyword_toolsets. Do not add new patterns here.
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
    # Action verbs that delegate service control to Sity.
    r"\breinicia\b|\barranca\b|\bdetén\b|\bdetener\b|\bpara\s+el\b"
    # Explicit tool reference or specific systemd service names.
    r"|\bsystemctl\b|\bsity-(?:backend|frontend|test)\b",
    # NOTE: bare \b(?:backend|frontend)\b intentionally removed.
    # Those words appear in casual speech ("el backend está raro") and must not
    # trigger cloud routing without an accompanying operational verb or service name.
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

_ACTION_ID_RE = re.compile(r"\bact_[a-fA-F0-9]{8}\b")


# ── Structural signal helpers ──────────────────────────────────────────────────

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


def message_mentions_action_id(message: str) -> bool:
    return bool(_ACTION_ID_RE.search(message))


def _toolsets_from_explicit_tool_names(message: str) -> list[list[dict]]:
    """Return toolsets whose tool name appears verbatim in the message."""
    normalized = message.lower()
    seen_ids: set[int] = set()
    result = []
    for tool_name, toolset in _TOOL_TO_TOOLSET.items():
        tid = id(toolset)
        if tool_name in normalized and tid not in seen_ids:
            seen_ids.add(tid)
            result.append(toolset)
    return result


def _legacy_keyword_toolsets(message: str) -> list[list[dict]]:
    """
    Legacy NL keyword fallback. Intentionally temporary.
    Do not add new keywords here — use structural signals instead.
    Kept until a reliable fallback-planner or broader default toolset is in place.
    """
    result = []

    if _GIT_RE.search(message):
        result.append(GIT_TOOLSET)

    if _SERVICE_CONFIG_RE.search(message):
        result.append(SERVICE_CONFIG_TOOLSET)
    elif _SERVICE_CONTROL_RE.search(message):
        result.append(SERVICE_CONTROL_TOOLSET)
    elif _SYSTEM_RE.search(message):
        result.append(SYSTEM_TOOLSET)

    if _SENSE_RE.search(message):
        result.append(SENSES_TOOLSET)

    if _DEBUG_RE.search(message):
        result.append(DEBUG_TOOLSET)

    if _PERSONALITY_FIELD_RE.search(message) and _PERSONALITY_ACTION_RE.search(message):
        result.append(PERSONALITY_TOOLSET)

    return result


# ── Public API ────────────────────────────────────────────────────────────────

def select_structural_toolsets_for_message(message: str) -> list[dict]:
    """Structural-only selection: tool names, file paths, action IDs.

    No NL keyword matching. Safe to test in isolation to measure legacy coverage.
    """
    selected = list(BASE_TOOLSET)

    for toolset in _toolsets_from_explicit_tool_names(message):
        selected.extend(toolset)

    if message_mentions_file_path(message):
        selected.extend(FILE_AGENT_TOOLSET)

    if message_mentions_action_id(message):
        selected.extend(PENDING_ACTION_TOOLSET)

    return _dedupe_tools(selected)


def select_toolset_for_message(message: str) -> list[dict]:
    selected = select_structural_toolsets_for_message(message)

    # Legacy NL keyword fallback — see _legacy_keyword_toolsets docstring.
    for toolset in _legacy_keyword_toolsets(message):
        selected.extend(toolset)

    return _dedupe_tools(selected)


# ---------------------------------------------------------------------------
# Metadata wrapper
# ---------------------------------------------------------------------------

# Maps toolset object identity → domain label for metadata.
# Defined after the toolset constants are imported.
_TOOLSET_DOMAIN: dict[int, str] = {
    id(FILE_AGENT_TOOLSET):      "file",
    id(GIT_TOOLSET):             "git",
    id(SERVICE_CONFIG_TOOLSET):  "service_config",
    id(SERVICE_CONTROL_TOOLSET): "service_control",
    id(SYSTEM_TOOLSET):          "system",
    id(SENSES_TOOLSET):          "senses",
    id(DEBUG_TOOLSET):           "debug",
    id(PERSONALITY_TOOLSET):     "personality",
    id(PENDING_ACTION_TOOLSET):  "pending_action",
}


@dataclass(frozen=True)
class ToolsetSelection:
    """Result of toolset selection with structural metadata."""

    tools: list[dict]
    """The selected tool list — identical to select_toolset_for_message output."""

    activated_domains: frozenset[str]
    """Non-base domains that were activated (e.g. 'file', 'git', 'system').
    Empty set means purely conversational (only BASE_TOOLSET selected)."""

    reasons: list[str]
    """Why each domain was activated.
    Format: 'explicit_tool_name:<name>', 'file_path_detected',
    'action_id_detected', 'keyword:<domain>'."""


def select_toolset_with_metadata(message: str) -> ToolsetSelection:
    """Select tools for a message and return structured metadata.

    *tools* is identical to select_toolset_for_message(message) — callers that
    only need the list should use that function instead.

    *activated_domains* is the set of non-base domains selected.  Use this
    (not len(tools)) to decide whether the turn requires cloud tool-calling.

    *reasons* lists why each domain was added, in activation order.
    """
    # Delegate tool list to the existing implementation for exact compatibility.
    tools = select_toolset_for_message(message)

    # Compute metadata independently (same logic, domain/reason tracking).
    activated_domains: set[str] = set()
    reasons: list[str] = []
    seen_ids: set[int] = set()

    def _record(toolset: list[dict], reason: str) -> None:
        tid = id(toolset)
        if tid in seen_ids:
            return
        seen_ids.add(tid)
        domain = _TOOLSET_DOMAIN.get(tid)
        if domain:
            activated_domains.add(domain)
            reasons.append(reason)

    # Structural: explicit tool names
    normalized = message.lower()
    for tool_name, toolset in _TOOL_TO_TOOLSET.items():
        if tool_name in normalized:
            _record(toolset, f"explicit_tool_name:{tool_name}")

    # Structural: file path detected
    if message_mentions_file_path(message):
        _record(FILE_AGENT_TOOLSET, "file_path_detected")

    # Structural: action ID detected
    if message_mentions_action_id(message):
        _record(PENDING_ACTION_TOOLSET, "action_id_detected")

    # Legacy NL keyword fallback
    if _GIT_RE.search(message):
        _record(GIT_TOOLSET, "keyword:git")
    if _SERVICE_CONFIG_RE.search(message):
        _record(SERVICE_CONFIG_TOOLSET, "keyword:service_config")
    elif _SERVICE_CONTROL_RE.search(message):
        _record(SERVICE_CONTROL_TOOLSET, "keyword:service_control")
    elif _SYSTEM_RE.search(message):
        _record(SYSTEM_TOOLSET, "keyword:system")
    if _SENSE_RE.search(message):
        _record(SENSES_TOOLSET, "keyword:senses")
    if _DEBUG_RE.search(message):
        _record(DEBUG_TOOLSET, "keyword:debug")
    if _PERSONALITY_FIELD_RE.search(message) and _PERSONALITY_ACTION_RE.search(message):
        _record(PERSONALITY_TOOLSET, "keyword:personality")

    return ToolsetSelection(
        tools=tools,
        activated_domains=frozenset(activated_domains),
        reasons=reasons,
    )


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
