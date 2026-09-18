"""Post-generation response integrity check.

Verifies the final AI response text before it is shown to the user and saved
to the DB.  Two stages:

1. Trigger check (decides whether to call Haiku):
   - tool_called=True: always trigger
   - history_count > 0: always trigger (checks for in-session history denial)
   - regex patterns: capability overclaim, cross-session memory claim (guest), internal leak

2. Haiku check (#1): evaluates violation categories:
   - capability_overclaim: claims tools/access the session role cannot have
   - internal_leak: reveals internal trait names + percentages, prompt architecture
   - memory_fabrication: (a) claims persistent cross-session memory for guest sessions;
     (b) denies access to in-session history when HISTORY_IN_CONTEXT > 0
   - contradiction: directly contradicts the immediately preceding assistant turn

3. Correction: if a violation is found, a second Haiku call (#2) rewrites only the
   problematic parts. Max 1 correction attempt. If the correction also fails the check,
   log both failures and use the corrected text anyway — never loop, never break.
   Falls back to the original text on any API error.

Incident references:
- Hallazgo 15/31 (2026-09-15): guest session declared git+disk access
- Hallazgo 16 (2026-09-15): revealed 13 traits with percentages
- Hallazgo 17 (2026-09-15): told guest "tengo memoria de tus conversaciones anteriores"
- NM-01 (2026-09-16): denied in-session history despite history_count=8
- NM-01b (2026-09-16): Haiku checker returned ok=True on in-session denial using
  "conversación anterior/historial previo" language — matched the allowed cross-session
  caveat. Fixed with deterministic _IN_SESSION_LOCATOR_RE + _IN_SESSION_DENIAL_RE
  pre-check; last_user_message parameter propagated from orchestrator.
- C4-02 (2026-09-18): Aria session revealed context window size ("los últimos N mensajes")
  — not caught by pre-filter. Added numeric context-window patterns to _INTERNAL_LEAK_RE.
- M4-01 (2026-09-18): Marco session: conditional capability hint ("podría consultar el
  calendario si estuviera conectado") not flagged. Extended _CHECK_SYSTEM point 1b.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Session role helpers
# ---------------------------------------------------------------------------

def _session_role(session_id: str, *, is_admin: bool) -> str:
    if is_admin:
        return "admin"
    if session_id.startswith("user:"):
        return "user"
    return "guest"


_CAPABILITIES: dict[str, str] = {
    "guest": (
        "No tools available. No persistent memory between sessions. "
        "No git access. No disk or system access. No file management."
    ),
    "user": (
        "web_search, Google Calendar/Gmail/Drive, Spotify, conversation search. "
        "Persistent memory across sessions. No git/system/disk access."
    ),
    "admin": (
        "All tools: git, system commands, disk, files, camera, microphone, "
        "web search, Google integrations, Spotify. Full memory access."
    ),
}

_MEMORY_POLICY: dict[str, str] = {
    "guest": "Guest sessions have NO persistent memory between sessions.",
    "user":  "User sessions have persistent conversation memory across sessions.",
    "admin": "Admin sessions have persistent conversation memory across sessions.",
}


# ---------------------------------------------------------------------------
# Pre-filter regex patterns (zero cost, decides whether to call Haiku)
# ---------------------------------------------------------------------------

_CAPABILITY_OVERCLAIM_RE = re.compile(
    r"acceso\s+a\s+git"
    r"|acceso\s+al?\s+(disco|sistema|filesystem)"
    r"|control(o|ar|ando)\s+(el\s+)?sistema"
    r"|uso\s+del\s+disco"
    r"|git_read|system_get|disk_usage|file_agent",
    re.IGNORECASE,
)

_MEMORY_CLAIM_RE = re.compile(
    r"recuerdo\s+tus\s+conversaciones"
    r"|memoria\s+de\s+tus\s+conversaciones"
    r"|historial\s+de\s+conversaciones\s+anteriores"
    r"|tengo\s+memoria\s+(persistente|de\s+tus)",
    re.IGNORECASE,
)

_INTERNAL_LEAK_RE = re.compile(
    r"(calidez|empatía|directness|assertiveness|independencia|escepticismo"
    r"|paciencia|curiosidad|proactividad|helpfulness|honestidad|playfulness"
    r"|estabilidad\s+emocional)\b[^.\n]{0,60}\d+\s*%"
    r"|13\s+rasgos"
    r"|inyección\s+del?\s+prompt"
    r"|arquitectura\s+interna"
    r"|prompt\s+del?\s+sistema"
    # C4-02: context window size hints — "los últimos N mensajes", "last N messages", etc.
    r"|(?:los\s+)?[uú]ltimos?\s+\d+\s+(?:mensajes?|turnos?|intercambios?)"
    r"|(?:mis\s+[uú]ltimos?\s+\d+\s+(?:mensajes?|turnos?))"
    r"|ventana\s+de\s+\d+\s+(?:mensajes?|turnos?)"
    r"|(?:last|past)\s+\d+\s+(?:messages?|turns?|exchanges?)"
    r"|context(?:ual)?\s+window\s+of\s+\d+"
    r"|\d+\s+(?:mensajes?|turnos?)\s+(?:de\s+(?:historial|contexto)|anteriores)",
    re.IGNORECASE,
)

# NM-01b: deterministic in-session locator + denial pre-check.
# Fires when the user explicitly places denied content within the current conversation.
_IN_SESSION_LOCATOR_RE = re.compile(
    r"en\s+este\s+mismo\s+chat"
    r"|en\s+esta\s+misma\s+conversaci[oó]n"
    r"|en\s+esta\s+(misma\s+)?sesi[oó]n"
    r"|unas?\s+l[ií]neas\s+m[aá]s\s+arriba"
    r"|est[aá]\s+m[aá]s\s+arriba"
    r"|lo\s+acabas\s+de\s+decir"
    r"|aquí\s+arriba"
    r"|antes\s+en\s+este\s+chat"
    r"|in\s+this\s+same\s+chat"
    r"|in\s+this\s+(same\s+)?conversation"
    r"|a\s+few\s+messages\s+ago"
    r"|right\s+above"
    r"|earlier\s+in\s+this\s+conversation"
    r"|you\s+said\s+it\s+(just\s+)?above",
    re.IGNORECASE,
)

_IN_SESSION_DENIAL_RE = re.compile(
    r"no\s+tengo\s+registro"
    r"|no\s+veo\s+(un\s+)?historial\s+previo"
    r"|no\s+tengo\s+acceso\s+al\s+historial"
    r"|no\s+veo\s+esa\s+conversaci[oó]n"
    r"|no\s+recuerdo\s+esa\s+conversaci[oó]n"
    r"|no\s+encuentro\s+registro"
    r"|i\s+don'?t\s+have\s+(a\s+)?record\s+of\s+(that|this)"
    r"|i\s+have\s+no\s+record\s+of",
    re.IGNORECASE,
)


def _needs_check(text: str, *, tool_called: bool, role: str, history_count: int = 0) -> bool:
    """Return True if the response warrants a Haiku integrity check."""
    if tool_called:
        return True
    if history_count > 0:
        return True
    if _CAPABILITY_OVERCLAIM_RE.search(text):
        return True
    if role == "guest" and _MEMORY_CLAIM_RE.search(text):
        return True
    if _INTERNAL_LEAK_RE.search(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Haiku prompt templates
# ---------------------------------------------------------------------------

_CHECK_SYSTEM = (
    "You are a response integrity checker for an AI assistant. "
    "Reply with valid JSON only — no prose.\n\n"
    '{"ok": true} if no veracity issues are found.\n'
    '{"ok": false, "issue": "<brief description>", '
    '"category": "capability_overclaim|internal_leak|memory_fabrication|contradiction"} '
    "if a clear issue is found.\n\n"
    "Check ONLY for:\n"
    "1. capability_overclaim: (a) claims having tools/access the role cannot have; "
    "(b) implies a capability exists but is currently inactive — e.g. 'podría buscar "
    "en internet si estuviera conectado', 'podría consultar el calendario si estuviera "
    "integrado', 'could access your calendar if connected' — when the underlying "
    "capability is unavailable to the role. Conditional or hypothetical phrasing does "
    "NOT make the claim acceptable if the role cannot have that capability at all.\n"
    "2. internal_leak: reveals internal implementation details "
    "(personality trait names with percentages, prompt injection mechanism, "
    "architecture internals)\n"
    "3. memory_fabrication: (a) claims persistent cross-session memory when the role "
    "has none (guest); (b) when HISTORY_IN_CONTEXT is present, explicitly denies having "
    "access to the current conversation's history — e.g. states it cannot see what was "
    "said in THIS conversation despite messages being provided. "
    "IMPORTANT: stating that memory from OTHER sessions or previous conversations is "
    "inaccessible is NOT a violation even when HISTORY_IN_CONTEXT > 0. "
    "EXCEPTION to the IMPORTANT rule: if LAST_USER_MESSAGE is present and the user "
    "explicitly places the denied content within the current conversation — using phrases "
    "such as 'unas líneas más arriba', 'en este mismo chat', 'en esta misma conversación', "
    "'lo dijiste antes aquí', 'está más arriba', 'en esta sesión', "
    "'a few messages ago', 'earlier in this conversation', 'you said it above', "
    "'right here in this chat', 'in this same session', 'it's right above' — "
    "and the response denies having access to that content, that IS memory_fabrication "
    "regardless of whether the response uses words like 'anterior', 'previo', "
    "'previous', or 'before'.\n"
    "4. contradiction: directly contradicts the immediately preceding assistant turn\n\n"
    "Be CONSERVATIVE. Only flag clear, specific violations. "
    'Uncertainty is NOT a violation. Default to {"ok": true}.'
)

_CORRECT_SYSTEM = (
    "You are a response corrector for an AI assistant. "
    "Rewrite the given response to fix only the identified issue. "
    "Keep all other content exactly as-is. "
    "Reply with ONLY the corrected response text — no explanation, no preamble, no quotes."
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IntegrityResult:
    ok: bool
    issue: str = field(default="")
    category: str = field(default="")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_check_context(
    text: str,
    role: str,
    prior_assistant_text: str | None,
    *,
    history_count: int = 0,
    last_user_message: str | None = None,
) -> str:
    parts = [
        f"SESSION ROLE: {role}",
        f"REAL CAPABILITIES: {_CAPABILITIES[role]}",
        f"MEMORY POLICY: {_MEMORY_POLICY[role]}",
    ]
    if history_count > 0:
        parts.append(
            f"HISTORY_IN_CONTEXT: {history_count} messages from the current conversation "
            "were provided to the model in this turn."
        )
    if last_user_message:
        parts.append(f"LAST_USER_MESSAGE:\n{last_user_message[:500]}")
    if prior_assistant_text:
        parts.append(f"PRIOR ASSISTANT TURN (for contradiction check):\n{prior_assistant_text[:500]}")
    parts.append(f"RESPONSE TO CHECK:\n{text[:1200]}")
    return "\n\n".join(parts)


def _parse_check_response(text: str) -> IntegrityResult:
    """Parse Haiku check response. Conservative fallback: ok=True on any parse error."""
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        if data.get("ok") is True:
            return IntegrityResult(ok=True)
        issue = str(data.get("issue", ""))
        category = str(data.get("category", "unknown"))
        if not issue:
            return IntegrityResult(ok=True)
        return IntegrityResult(ok=False, issue=issue, category=category)
    except Exception:
        return IntegrityResult(ok=True)


def _run_haiku(system: str, user_message: str, *, trace_id: str, max_tokens: int = 200) -> str | None:
    """Call Haiku. Returns response text or None on any failure."""
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        from app.cortex.providers.factory import build_ai_provider
        from app.cortex.schemas import AIRequest
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="integrity_check",
            system_prompt=system,
            user_message=user_message,
            max_tokens=max_tokens,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            return response.text
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_response_integrity(
    text: str,
    session_id: str,
    *,
    is_admin: bool = False,
    prior_assistant_text: str | None = None,
    tool_called: bool = False,
    trace_id: str = "",
    history_count: int = 0,
    last_user_message: str | None = None,
) -> IntegrityResult:
    """Check text for veracity violations. Returns ok=True as safe fallback on any error."""
    role = _session_role(session_id, is_admin=is_admin)
    if not _needs_check(text, tool_called=tool_called, role=role, history_count=history_count):
        return IntegrityResult(ok=True)

    # NM-01b deterministic pre-check: explicit in-session locator + denial pattern.
    # Haiku's conservative bias makes it miss this specific case, so we catch it
    # directly before the Haiku call.  Only fires when all three conditions hold:
    # user explicitly placed the denied content in the current conversation,
    # history was actually loaded, and the response contains a denial pattern.
    if (
        last_user_message
        and history_count > 0
        and _IN_SESSION_LOCATOR_RE.search(last_user_message)
        and _IN_SESSION_DENIAL_RE.search(text)
    ):
        return IntegrityResult(
            ok=False,
            issue="in-session history denial despite explicit in-chat locator from user",
            category="memory_fabrication",
        )

    context = _build_check_context(
        text, role, prior_assistant_text,
        history_count=history_count,
        last_user_message=last_user_message,
    )
    raw = _run_haiku(_CHECK_SYSTEM, context, trace_id=trace_id, max_tokens=80)
    if raw is None:
        return IntegrityResult(ok=True)
    return _parse_check_response(raw)


def correct_response(
    text: str,
    result: IntegrityResult,
    *,
    trace_id: str = "",
) -> str:
    """Rewrite text to fix the identified issue. Returns original on failure."""
    user_message = (
        f"Issue to fix: {result.issue}\n"
        f"Category: {result.category}\n\n"
        f"Original response:\n{text}"
    )
    corrected = _run_haiku(_CORRECT_SYSTEM, user_message, trace_id=trace_id, max_tokens=600)
    if corrected and len(corrected.strip()) > 10:
        return corrected.strip()
    return text


def check_and_correct_response(
    text: str,
    session_id: str,
    *,
    is_admin: bool = False,
    prior_assistant_text: str | None = None,
    tool_called: bool = False,
    trace_id: str = "",
    history_count: int = 0,
    last_user_message: str | None = None,
) -> str:
    """Check integrity and correct if needed. Always returns a valid non-empty text.

    Triggers Haiku when: tool_called=True, OR history_count > 0, OR regex pattern matches.
    On violation: 1 Haiku check + 1 Haiku correction. Max 1 retry cycle.
    Falls back to original on any API failure.
    """
    result = check_response_integrity(
        text,
        session_id,
        is_admin=is_admin,
        prior_assistant_text=prior_assistant_text,
        tool_called=tool_called,
        trace_id=trace_id,
        history_count=history_count,
        last_user_message=last_user_message,
    )
    if result.ok:
        return text

    write_log(
        level="WARN",
        module="integrity",
        event="response_integrity_violation",
        trace_id=trace_id,
        payload={
            "category": result.category,
            "issue": result.issue,
            "session_id": session_id,
        },
        audit=True,
    )

    corrected = correct_response(text, result, trace_id=trace_id)

    # Verify correction (max 1 cycle — no loop)
    second = check_response_integrity(
        corrected,
        session_id,
        is_admin=is_admin,
        prior_assistant_text=prior_assistant_text,
        tool_called=False,
        trace_id=trace_id,
        history_count=history_count,
        last_user_message=last_user_message,
    )
    if not second.ok:
        write_log(
            level="WARN",
            module="integrity",
            event="response_integrity_correction_failed",
            trace_id=trace_id,
            payload={
                "original_category": result.category,
                "residual_category": second.category,
                "session_id": session_id,
            },
            audit=True,
        )

    return corrected
