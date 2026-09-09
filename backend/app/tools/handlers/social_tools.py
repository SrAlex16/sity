"""social_tools.py — social_recall_impression handler (Remake Fase 3).

Returns Sity's qualitative impression of a third-party user (B) when
the current interlocutor (A) asks about them by display_name.

Privacy model
─────────────
All filtering happens here in the handler, never in the prompt.

  A = current session (session_id must be "user:N")
  B = target user, resolved by display_name (case-insensitive, exact)

Disclosure level = trust_avg_A × trust_avg_B
  < 0.05  → LOW   : only the affinity label, no further detail
  0.05–0.20→ MEDIUM: label + one-line about Sity's familiarity with B
  ≥ 0.20  → HIGH  : label + familiarity + one extra qualitative line

trust_avg = (trust_honesty + trust_intentions + trust_competence + trust_reliability) / 4

The formula trust_avg_A × trust_avg_B acts as a double gate:
  • A must have earned Sity's trust (established relationship) AND
  • Sity must actually know B (not just a few turns of history)
  before any nuance is shared.

Absolute limit (enforced at every level):
  NEVER include content from B's messages, specific facts, or any
  concrete/verifiable information about B — only qualitative impressions
  derived from affinity/trust values.
"""
from __future__ import annotations

from sqlalchemy import text as sa_text

from app.chat.prompt_context import _affinity_label, _familiarity_label
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
    affinity_b: float,
    familiarity_b: float,
    trust_avg_b: float,
    disclosure: float,
) -> str:
    label = _affinity_label(affinity_b)

    if disclosure < 0.05:
        return (
            f"Tengo una impresión de afinidad {label} de esa persona, "
            "pero no tenemos suficiente historia compartida para que me extienda más."
        )

    familiarity_label = _familiarity_label(familiarity_b)
    if disclosure < 0.20:
        return (
            f"Tengo una impresión de afinidad {label} de {display_name}. "
            f"Mi nivel de conocimiento de esa persona es: {familiarity_label}."
        )

    # HIGH — one extra qualitative line based on trust_avg_b
    if trust_avg_b >= 0.65:
        extra = "Tenemos una relación bastante estable."
    elif trust_avg_b >= 0.45:
        extra = "Nos conocemos, aunque hay margen para que la relación madure."
    else:
        extra = "Aún estoy formándome una impresión más completa."

    return (
        f"Tengo una impresión de afinidad {label} de {display_name}. "
        f"Mi nivel de conocimiento de esa persona es: {familiarity_label}. "
        f"{extra}"
    )


@tool_handler("social_recall_impression")
def handle_social_recall_impression(ctx: ToolContext) -> ToolExecutionResult:
    session_id: str = ctx.executor.session_id

    # Guest check — no SocialProfile, no impression available.
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

    # Resolve A's trust_avg
    row_a = session.execute(
        sa_text(
            "SELECT trust_honesty, trust_intentions, trust_competence, trust_reliability"
            " FROM socialprofile WHERE user_id = :uid"
        ),
        {"uid": user_id_a},
    ).fetchone()
    trust_avg_a: float = (sum(row_a) / 4.0) if row_a else 0.0

    # Resolve B by display_name (case-insensitive exact match)
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

    if user_id_b == user_id_a:
        return _ok("Estás preguntando por ti mismo.")

    row_b = session.execute(
        sa_text(
            "SELECT affinity, familiarity,"
            " trust_honesty, trust_intentions, trust_competence, trust_reliability"
            " FROM socialprofile WHERE user_id = :uid"
        ),
        {"uid": user_id_b},
    ).fetchone()

    if row_b is None:
        return _ok(f"No tengo ninguna impresión formada sobre {username} todavía.")

    affinity_b: float = row_b[0]
    familiarity_b: float = row_b[1]
    trust_avg_b: float = (row_b[2] + row_b[3] + row_b[4] + row_b[5]) / 4.0

    disclosure = trust_avg_a * trust_avg_b
    text = _build_impression(username, affinity_b, familiarity_b, trust_avg_b, disclosure)
    return _ok(text)
