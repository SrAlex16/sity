"""social_tools.py — social_recall_impression handler.

Returns Sity's qualitative impression of a third-party user (B) when
the current interlocutor (A) asks about them by display_name.

Privacy model
─────────────
All filtering happens here in the handler, never in the prompt.

  A = current session (session_id must be "user:N")
  B = target user, resolved by display_name (case-insensitive, exact)

Disclosure level = trust_A × trust_B
  < 0.05  → LOW   : only the opinion label, no further detail
  0.05–0.20→ MEDIUM: label + one-line about Sity's familiarity with B
  ≥ 0.20  → HIGH  : label + familiarity + one extra qualitative line

Absolute limit (enforced at every level):
  NEVER include content from B's messages, specific facts, or any
  concrete/verifiable information about B — only qualitative impressions
  derived from opinion/trust values.

The formula trust_A × trust_B acts as a double gate:
  • A must have earned Sity's trust (long, stable relationship) AND
  • Sity must actually know B (not just a few turns of history)
  before any nuance is shared. When either party is new, disclosure stays
  at the generic floor regardless of what A claims about their own trust.
"""
from __future__ import annotations

from sqlalchemy import text as sa_text

from app.chat.prompt_context import _opinion_label, _trust_label
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


def _ok(text: str, tool_name: str = "social_recall_impression") -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=True,
        message=text,
        updated_parameters=[],
        raw_result={"success": True, "text": text, "local_final": True,
                    "local_model": "tool-policy"},
    )


def _err(text: str, tool_name: str = "social_recall_impression") -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=False,
        message=text,
        updated_parameters=[],
        raw_result={"success": False, "text": text, "local_final": True,
                    "local_model": "tool-policy"},
    )


def _build_impression(
    display_name: str,
    opinion_b: float,
    trust_b: float,
    disclosure: float,
) -> str:
    label = _opinion_label(opinion_b)

    if disclosure < 0.05:
        return (
            f"Tengo una impresión {label} de esa persona, "
            "pero no tenemos suficiente historia compartida para que me extienda más."
        )

    familiarity_b = _trust_label(trust_b)
    if disclosure < 0.20:
        return (
            f"Tengo una impresión {label} de {display_name}. "
            f"Mi nivel de conocimiento de esa persona es: {familiarity_b}."
        )

    # HIGH — one extra qualitative line based on trust_b stability signal
    if trust_b >= 0.50:
        extra = "Tenemos una relación bastante estable."
    elif trust_b >= 0.20:
        extra = "Nos conocemos, aunque hay margen para que la relación madure."
    else:
        extra = "Aún estoy formándome una impresión más completa."

    return (
        f"Tengo una impresión {label} de {display_name}. "
        f"Mi nivel de conocimiento de esa persona es: {familiarity_b}. "
        f"{extra}"
    )


@tool_handler("social_recall_impression")
def handle_social_recall_impression(ctx: ToolContext) -> ToolExecutionResult:
    session_id: str = ctx.executor.session_id

    # Guest check — no SocialProfile, no trust, no disclosure.
    if not session_id.startswith("user:"):
        return _ok("No tengo memoria de relaciones en esta sesión.")

    try:
        user_id_a = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return _err("No pude identificar al interlocutor actual.")

    username = str(ctx.tool_input.get("username", "")).strip()
    if not username:
        return _err("Se requiere el parámetro username.")

    session = ctx.executor.session

    # Resolve A's profile (trust_A).
    row_a = session.execute(
        sa_text("SELECT opinion, trust FROM socialprofile WHERE user_id = :uid"),
        {"uid": user_id_a},
    ).fetchone()
    trust_a: float = row_a[1] if row_a else 0.0

    # Resolve B by display_name (case-insensitive exact match).
    row_user_b = session.execute(
        sa_text(
            "SELECT id FROM user"
            " WHERE lower(display_name) = lower(:name) AND is_active = 1"
            " LIMIT 1"
        ),
        {"name": username},
    ).fetchone()

    if row_user_b is None:
        return _ok(f'No conozco a nadie con el nombre "{username}".')

    user_id_b: int = row_user_b[0]

    # A == B: someone asking about themselves.
    if user_id_b == user_id_a:
        return _ok("Estás preguntando por ti mismo.")

    # B's profile.
    row_b = session.execute(
        sa_text("SELECT opinion, trust FROM socialprofile WHERE user_id = :uid"),
        {"uid": user_id_b},
    ).fetchone()

    if row_b is None:
        return _ok(f"No tengo ninguna impresión formada sobre {username} todavía.")

    opinion_b: float = row_b[0]
    trust_b: float = row_b[1]

    disclosure = trust_a * trust_b
    text = _build_impression(username, opinion_b, trust_b, disclosure)
    return _ok(text)
