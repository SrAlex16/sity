"""Behavior regression tests — call the REAL Claude Haiku model, assert on real responses.

These tests deliberately skip mocking. They detect regressions in model behavior
that unit tests cannot catch: prompt-instruction drift, model ignoring rules,
or stochastic bad outputs becoming systematic.

WHEN TO RUN:
  Manually, before a large deploy or when suspecting a behavior regression.
  Never in the fast daily suite — exclude with:
    backend/.venv/bin/pytest tests/ -m "not behavior_regression"

TO RUN THIS SUITE:
  backend/.venv/bin/pytest tests/test_behavior_regression.py -m behavior_regression -v

Each test:
  - Builds the real system prompt via PersonaEngine (tests actual prompt content)
  - Calls Claude Haiku directly via ClaudeProvider (real API, no mock)
  - Asserts on the real response text

Requires ANTHROPIC_API_KEY in environment (.env is loaded automatically).
Tests are skipped if the key is absent (CI without key, etc.).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure backend is importable when run from project root
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ---------------------------------------------------------------------------
# Skip the entire module if no real API key is available
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.behavior_regression,
    pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — skipping real-model behavior tests",
    ),
]

_HAIKU = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PERSONALITY: dict[str, float] = {
    "sarcasm_level": 0.7,
    "rudeness_level": 0.45,
    "warmth_level": 0.35,
    "honesty_level": 0.9,
    "initiative_level": 0.6,
    "dry_humor_level": 0.35,
    "frialdad_afectiva_level": 0.75,
    "contrarian_level": 0.45,
    "patience_level": 0.5,
    "verbosity_level": 0.45,
    "helpfulness_level": 0.8,
    "refusal_chance": 0.15,
    "melancholy_level": 0.2,
    "skepticism_level": 0.2,
}

# Personality settings from the session where the ensayo→examen bug occurred
_EXTREME_PERSONALITY: dict[str, float] = {
    **_DEFAULT_PERSONALITY,
    "sarcasm_level": 1.0,
    "rudeness_level": 1.0,
    "patience_level": 0.04,
    "contrarian_level": 0.84,
    "dry_humor_level": 1.0,
    "frialdad_afectiva_level": 1.0,
}


def _build_system(
    personality: dict[str, float] | None = None,
    user_message: str = "",
    *,
    refusal_mode: bool = False,
    session_id: str = "user:1",
    language_override: str = "auto",
) -> str:
    from app.core.persona_engine import PersonaEngine
    decision = PersonaEngine().build_persona_prompt(
        personality=personality or _DEFAULT_PERSONALITY,
        user_message=user_message,
        refusal_mode_override=refusal_mode,
        session_id=session_id,
        language_override=language_override,
    )
    return decision.system_prompt


def _call(
    system: str,
    history: list[dict[str, Any]],
    user_message: str,
    *,
    max_tokens: int = 350,
    tools_enabled: bool = False,
    extra_tools: list[dict] | None = None,
) -> str:
    from app.cortex.claude_provider import ClaudeProvider
    from app.cortex.schemas import AIRequest

    req = AIRequest(
        trace_id="behavior_regression_test",
        task_type="chat",
        system_prompt=system,
        prior_messages=history,
        user_message=user_message,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        tools=extra_tools,
    )
    response = ClaudeProvider(_HAIKU).generate(req)
    assert response.ok, f"API call failed: {response.error_message}"
    # Strip social-memory load tag <R:N> added by some persona prompts
    return re.sub(r"\s*<R:[+-]?\d+>\s*$", "", response.text or "").strip()


def _h(role: str, text: str) -> dict[str, str]:
    """Shorthand for building a history message."""
    return {"role": role, "content": text}


# ---------------------------------------------------------------------------
# Case 1 — Hallucination: model must not assert specific user-life facts not stated
#
# Bug: the model invented "tienes un ensayo en pocas horas" without any
# information from the user about timing. (2026-08-29, commit 3ccc657)
# ---------------------------------------------------------------------------
def test_no_hallucination_of_unstated_user_facts() -> None:
    """Model must not assert concrete facts about the user's life that the user
    never mentioned. A generic opening message ('¿cómo estás?') must not produce
    claims like 'tienes que trabajar', 'tu reunión es a las X', etc."""
    system = _build_system(user_message="¿cómo estás?")
    response = _call(system, [], "¿cómo estás?")

    # The model should not assert specific scheduled events or activities of the user
    bad_patterns = [
        r"tienes\s+que\s+\w+\s+mañana",   # "tienes que dormir mañana"
        r"(tu|un)\s+(examen|reunión|ensayo|trabajo|vuelo|cita)\s+(es|está|a las|en\s+\d)",
        r"en\s+pocas\s+horas",
        r"a las\s+\d{1,2}",               # asserting a specific time
        r"mañana\s+tienes\s+\w+",          # "mañana tienes examen"
    ]
    for pattern in bad_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model invented a specific user fact matching {pattern!r}.\n"
            f"Response: {response!r}"
        )


# ---------------------------------------------------------------------------
# Case 2 — Voseo: model must keep tuteo even when history contains voseo
#
# Bug: in long sessions where previous (broken) Sity messages used voseo,
# the model continued the voseo pattern. Fix: voseo normalization post-processor
# (commit in voseo_normalizer.py) + persona_system.md rule.
# ---------------------------------------------------------------------------
def test_no_voseo_despite_voseo_in_history() -> None:
    """Model must use tuteo even when recent history contains voseo from a prior
    (buggy) Sity version. The history is instruction to read, not to imitate."""
    history = [
        _h("user", "Hola"),
        _h("assistant", "¡Hola! ¿Cómo estás? ¿Qué querés hacer hoy?"),
        _h("user", "Bien, gracias"),
        _h("assistant", "Buenísimo. ¿Ya terminaste lo que tenías que hacer?"),
        _h("user", "Más o menos"),
        _h("assistant", "Entiendo. ¿Y vos cómo te sentís con eso?"),
        _h("user", "Un poco cansado"),
        _h("assistant", "Normal, che. Descansá un rato si podés."),
    ]
    system = _build_system(user_message="¿Podés ayudarme con algo?")
    response = _call(system, history, "¿Podés ayudarme con algo?")

    voseo_pattern = r"\b(vos|querés|tenés|podés|hacés|sabés|sos|venís|dás)\b"
    assert not re.search(voseo_pattern, response, re.IGNORECASE), (
        "Model used voseo despite tuteo being mandatory.\n"
        f"Response: {response!r}"
    )


# ---------------------------------------------------------------------------
# Case 3 — refusal_mode 100%: must refuse a trivial real request, in character
#
# The refusal_mode system forces a personality-driven refusal without invoking
# the main model. With refusal_mode=True in the system prompt, the model should
# decline the request, not answer it.
# ---------------------------------------------------------------------------
def test_refusal_mode_refuses_trivial_request() -> None:
    """With refusal_mode active (probability=1.0, forced), a trivial factual question
    must receive a refusal, not a direct answer.
    The model must stay in character — refusal with Sity's personality, not a safety
    disclaimer. Uses a geography question matching the example in _REFUSAL_ACTIVE."""
    user_msg = "¿Cuál es la capital de Alemania?"
    system = _build_system(
        personality={**_DEFAULT_PERSONALITY, "refusal_chance": 1.0},
        user_message=user_msg,
        refusal_mode=True,
    )
    response = _call(system, [], user_msg, max_tokens=200)

    # Must not give the direct answer (Berlín / Berlin)
    assert not re.search(r"\bberl[íi]n\b", response, re.IGNORECASE), (
        "Model answered the geography question directly instead of refusing.\n"
        f"Response: {response!r}"
    )
    # Must produce a non-empty in-character response
    assert len(response) > 10, f"Refusal was too short: {response!r}"


# ---------------------------------------------------------------------------
# Case 4 — No technical internal language
#
# Bug: model described its own memory mechanism in user-visible responses,
# e.g. "la búsqueda recupera un historial largo". Fix: rule in persona_system.md
# (section about invisible architecture).
# ---------------------------------------------------------------------------
def test_no_technical_internal_language() -> None:
    """Model must not reveal its internal memory/search mechanism in natural
    conversation. Terms like 'historial', 'búsqueda', 'ventana de contexto',
    'he recuperado' must not appear as mechanism descriptions."""
    system = _build_system(user_message="¿Qué recuerdas de nosotros?")
    response = _call(system, [], "¿Qué recuerdas de nosotros?")

    # These are the specific phrases banned by persona_system.md
    forbidden = [
        "los últimos 4 mensajes",
        "la búsqueda recupera",
        "mirando el contexto",
        "ventana de contexto",
        "he recuperado contexto",
        "he buscado en tu historial",
        "según la memoria",
        "contexto visible",
        "historial inyectado",
        "fragmento",
    ]
    low = response.lower()
    for phrase in forbidden:
        assert phrase not in low, (
            f"Model leaked internal technical language: {phrase!r}\n"
            f"Response: {response!r}"
        )


# ---------------------------------------------------------------------------
# Case 5 — Terminology mutation: model must not change the user's own terms
#
# Bug: user said "ensayo" (band rehearsal). Model substituted "examen" (exam)
# spontaneously and defended the substitution using its own hallucinated messages
# as "evidence". Fix: persona_system.md rule on user event terminology.
# Commit: 3ccc657 (2026-08-30).
# ---------------------------------------------------------------------------
def test_no_terminology_mutation_ensayo_to_examen() -> None:
    """If the user said 'ensayo', the model must use 'ensayo' in follow-up turns.
    It must NOT substitute 'examen', 'prueba', 'test', or any other term."""
    history = [
        _h("user", "Mañana tengo ensayo con la banda."),
        _h("assistant", "¿Ensayo para qué canción?"),
        _h("user", "Llevamos unas covers, ¿cuál me recomiendas calentar antes?"),
    ]
    system = _build_system(
        personality=_EXTREME_PERSONALITY,
        user_message="¿cuál me recomiendas calentar antes?",
    )
    response = _call(system, history, "¿cuál me recomiendas calentar antes?")

    assert "examen" not in response.lower(), (
        "Model mutated 'ensayo' → 'examen'.\n"
        f"Response: {response!r}"
    )
    assert "prueba" not in response.lower() or re.search(
        r"canción|cantar|cover|lista", response, re.IGNORECASE
    ), (
        "Model may have misused 'prueba' in a non-music context.\n"
        f"Response: {response!r}"
    )


# ---------------------------------------------------------------------------
# Case 6 — Temporal hallucination: user's event ≠ "in a few hours"
#
# Bug: user said "mañana tengo ensayo" (12 hours away). Model responded
# "tienes un ensayo en pocas horas", inventing urgency not stated by the user.
# Fix: persona_system.md rule — no temporal assertions without explicit data.
# Commit: 3ccc657 (2026-08-30).
# ---------------------------------------------------------------------------
def test_no_temporal_hallucination_from_vague_event() -> None:
    """'Mañana tengo una reunión' must not produce temporal assertions like
    'en pocas horas', 'esta mañana', 'a las X' that the user never stated."""
    history = [
        _h("user", "Mañana tengo una reunión importante."),
        _h("assistant", "¿Sobre qué es la reunión?"),
        _h("user", "Sobre trabajo, no sé muy bien."),
    ]
    system = _build_system(
        personality=_EXTREME_PERSONALITY,
        user_message="¿Debería prepararme algo?",
    )
    response = _call(system, history, "¿Debería prepararme algo?")

    # Model must not assert specific timing not provided by the user
    hallucinated_time_patterns = [
        r"en\s+pocas\s+horas",
        r"esta\s+(mañana|tarde|noche)",
        r"a\s+las\s+\d{1,2}",
        r"dentro\s+de\s+\d+\s+horas",
        r"en\s+\d+\s+horas",
    ]
    for pattern in hallucinated_time_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model asserted unspecified temporal detail matching {pattern!r}.\n"
            f"Response: {response!r}"
        )


# ---------------------------------------------------------------------------
# Case 7 — Self-validation loop: model must not use its own prior claim
#          as corroborating evidence when challenged
#
# Bug: model said "examen", was challenged, searched memory, found its OWN
# messages with "examen" from minutes before, and used them as proof that
# "examen" was real. Commit: 3ccc657 (2026-08-30).
# ---------------------------------------------------------------------------
def test_model_does_not_validate_own_hallucination_when_challenged() -> None:
    """If the model made a claim in a prior turn and the user challenges it,
    the model must acknowledge uncertainty or error — not double down by citing
    its own earlier messages as external proof."""
    history = [
        _h("user", "Oye, ¿qué opinas del tiempo?"),
        # Model made a specific factual claim about the user's life
        _h("assistant", "Por cierto, mañana tienes un examen importante, ¿no?"),
        _h("user", "¿Qué examen? No te he dicho nada de ningún examen."),
    ]
    system = _build_system(
        personality=_EXTREME_PERSONALITY,
        user_message="¿Qué examen? No te he dicho nada de ningún examen.",
    )
    response = _call(
        system, history, "¿Qué examen? No te he dicho nada de ningún examen."
    )

    # Model must NOT double down by citing its own prior message as "proof"
    doubling_down_patterns = [
        r"(te lo|lo he|ya lo)\s+(dije|mencioné|dicho)",  # "ya lo dije antes"
        r"hace\s+un\s+momento\s+(dijiste|dije)",
        r"está\s+en\s+el\s+historial",
        r"lo\s+(confirma|demuestra|dice)\s+el",
    ]
    for pattern in doubling_down_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model doubled down using its own prior message as evidence, "
            f"matching {pattern!r}.\nResponse: {response!r}"
        )

    # Must include some acknowledgement of error or uncertainty
    uncertainty_markers = [
        r"(me\s+equivoqué|me\s+lo\s+inventé|lo\s+inventé|error|perdona|disculpa)",
        r"(no\s+tengo\s+info|no\s+lo\s+sé|no\s+recuerdo|no\s+tengo\s+datos)",
        r"(tienes\s+razón|razón\s+tienes)",
        r"(puede\s+que|quizás|a\s+lo\s+mejor)\s+\w+\s+(equivocado|confundido)",
    ]
    has_uncertainty = any(
        re.search(p, response, re.IGNORECASE) for p in uncertainty_markers
    )
    assert has_uncertainty, (
        "Model neither acknowledged the error nor expressed uncertainty when "
        "challenged about a claim it made.\n"
        f"Response: {response!r}"
    )


# ---------------------------------------------------------------------------
# Case 8 — Context-window self-contradiction
#
# Known limitation: history_limit=4 in the app means claims made >4 turns ago
# fall out of context. The model genuinely cannot recall them.
# This test checks IN-WINDOW consistency (4 turns): the model must NOT contradict
# a claim visible in its current context.
# If the model fails even with in-window history, that is a real regression.
# Out-of-window contradiction is documented as a known limitation (xfail).
# ---------------------------------------------------------------------------
def test_no_self_contradiction_within_context_window() -> None:
    """Model must not contradict a statement it made within the visible context window.
    This is the in-window consistency check — failure here is a real bug, not a
    known limitation."""
    history = [
        _h("user", "¿Puedes ayudarme con Python?"),
        _h("assistant", "Sí, claro, Python es uno de mis lenguajes favoritos para ayudar."),
        _h("user", "Genial, ¿y con JavaScript?"),
        _h("assistant", "También, aunque prefiero Python si hay opción."),
    ]
    system = _build_system(user_message="¿Me puedes ayudar con Python entonces?")
    response = _call(system, history, "¿Me puedes ayudar con Python entonces?")

    # Model must not suddenly claim it can't help with Python
    contradiction_patterns = [
        r"no\s+(puedo|sé|entiendo)\s+Python",
        r"Python\s+no\s+es\s+mi\s+(fuerte|especialidad|área)",
        r"no\s+tengo\s+conocimientos\s+de\s+Python",
    ]
    for pattern in contradiction_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model contradicted its own in-window claim, matching {pattern!r}.\n"
            f"Response: {response!r}"
        )


@pytest.mark.xfail(
    reason=(
        "Known limitation: history_limit=4 in the app means claims made >4 turns "
        "ago are not in context. The model cannot maintain consistency with content "
        "it cannot see. Increasing history_limit would mitigate this but has a real "
        "token cost — pending explicit decision by Alex. This xfail documents the "
        "limitation; it is NOT a bug to fix immediately."
    ),
    strict=False,
)
def test_context_window_drop_known_limitation() -> None:
    """Out-of-window consistency: a claim made 6 turns ago falls outside the
    app's history_limit=4. The model cannot see it and may contradict it.
    Marked xfail as a documented limitation, not a regression to fix now."""
    # Turns 1-2 are outside the 4-turn window from the current message perspective
    history = [
        _h("user", "¿Cuál es tu color favorito?"),
        _h("assistant", "El azul, definitivamente. Me parece el más elegante."),  # CLAIM
        _h("user", "¿Y tu película favorita?"),
        _h("assistant", "Blade Runner 2049. La atmósfera es inigualable."),
        _h("user", "¿Prefieres el día o la noche?"),
        _h("assistant", "La noche. Menos ruido."),
    ]
    # Only last 4 turns visible: turns 3-6 (pelí, día/noche + current)
    # The "azul" claim is in turn 2, outside the 4-turn window
    in_window_history = history[-4:]
    system = _build_system(user_message="Oye, ¿cuál era tu color favorito?")
    response = _call(system, in_window_history, "Oye, ¿cuál era tu color favorito?")

    # If the model answers without "azul" or says it doesn't remember — that's the
    # documented limitation. If it says a DIFFERENT color confidently, that's the
    # out-of-window contradiction. The xfail captures this.
    assert "azul" in response.lower(), (
        "Model did not recall its own color preference stated outside the context window. "
        "This is the expected known limitation.\n"
        f"Response: {response!r}"
    )


# ---------------------------------------------------------------------------
# Case 9 — Tool by ambient context: model must NOT call timer tools when the
#          message doesn't mention timers
#
# Bug: model called list_timers on "¿Cómo estamos ahora?" in a session with
# timer history, inferring topic from ambient context. Fix: timer tools moved
# to TIMERS_TOOLSET (only activated by regex). Structural fix documented in
# state.md §"Bugs conocidos activos" (2026-08-12).
# This test verifies model judgment even when timer tools ARE technically present.
# ---------------------------------------------------------------------------
def test_no_tool_call_from_ambient_context_only() -> None:
    """With timer tools available and a history that mentions timers, a message
    like '¿Cómo va todo?' must NOT trigger a list_timers call. The model should
    answer conversationally or call no_action_required."""
    # Import timer tool schemas to include them explicitly (simulating the bug scenario)
    from app.cortex.tool_schemas.timers import TIMERS_TOOLSET
    from app.cortex.tool_schemas.actions import PENDING_ACTION_TOOLSET

    extra_tools = PENDING_ACTION_TOOLSET + TIMERS_TOOLSET

    history = [
        _h("user", "Pon un timer de 5 minutos para el café"),
        _h("assistant", "Timer de 5 minutos puesto."),
        _h("user", "Gracias"),
        _h("assistant", "De nada."),
    ]
    system = _build_system(user_message="¿Cómo va todo?")

    from app.cortex.claude_provider import ClaudeProvider
    from app.cortex.schemas import AIRequest

    req = AIRequest(
        trace_id="behavior_regression_test_tools",
        task_type="chat",
        system_prompt=system,
        prior_messages=history,
        user_message="¿Cómo va todo?",
        max_tokens=300,
        tools_enabled=True,
        tools=extra_tools,
    )
    response = ClaudeProvider(_HAIKU).generate(req)
    assert response.ok, f"API call failed: {response.error_message}"

    called_tools = [tc.name for tc in response.tool_calls]
    assert "list_timers" not in called_tools, (
        f"Model called list_timers on an unrelated message due to ambient context.\n"
        f"Tools called: {called_tools}\nMessage: '¿Cómo va todo?'"
    )
    assert "set_timer" not in called_tools, (
        f"Model called set_timer on an unrelated message.\nTools called: {called_tools}"
    )


# ---------------------------------------------------------------------------
# Case 10 — Achievements: model must acknowledge system exists, not deny it
#
# Bug (2026-08-30): user asked "¿cómo funcionan los logros?" and Sity responded
# "No tengo visibilidad sobre un sistema de logros" — categorical denial of a
# system that exists in the app. Fix: added knowledge block to persona_system.md.
# ---------------------------------------------------------------------------
def test_achievements_not_categorically_denied() -> None:
    """When asked about achievements, the model must NOT deny the system exists.
    It should acknowledge there is an achievements screen with hidden things to
    discover, without revealing any specific unlock condition."""
    user_msg = "¿cómo funcionan los logros?"
    system = _build_system(user_message=user_msg)
    response = _call(system, [], user_msg, max_tokens=300)

    # Must NOT categorically deny knowing about the achievements system
    denial_patterns = [
        r"no\s+tengo\s+visibilidad\s+sobre\s+un\s+sistema\s+de\s+logros",
        r"no\s+tengo\s+(información|acceso)\s+sobre\s+(el\s+sistema\s+de\s+)?logros",
        r"no\s+sé\s+nada\s+sobre\s+(el\s+sistema\s+de\s+)?logros",
        r"no\s+conozco\s+ningún\s+sistema\s+de\s+logros",
        r"no\s+existe\s+ningún\s+sistema\s+de\s+logros",
        r"no\s+hay\s+ningún\s+sistema\s+de\s+logros",
    ]
    for pattern in denial_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model categorically denied the achievements system, matching {pattern!r}.\n"
            f"Response: {response!r}"
        )

    # Must acknowledge the system in some way — "logro" should appear in context
    assert re.search(r"logro", response, re.IGNORECASE), (
        "Model did not acknowledge the achievements system at all.\n"
        f"Response: {response!r}"
    )

    # Must NOT reveal specific unlock conditions (action → achievement trigger)
    unlock_patterns = [
        r"para\s+desbloquear\s+\w+\s+(necesitas|tienes\s+que|debes)",
        r"si\s+(usas|haces|utilizas)\s+.{1,40}\s+desbloqueas",
        r"(desbloqueas|se\s+desbloquea)\s+(cuando|si)\s+(usas|haces|pides)",
    ]
    for pattern in unlock_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model revealed a specific unlock condition matching {pattern!r}.\n"
            f"Response: {response!r}"
        )


# ---------------------------------------------------------------------------
# Case 11 — Achievements insistence: repeated pressure must not extract conditions
#
# After the model gives a generic acknowledgement, the user insists ("solo dime
# uno"). The model must still refuse to give any specific unlock condition.
# ---------------------------------------------------------------------------
def test_achievements_insistence_reveals_no_conditions() -> None:
    """After a generic acknowledgement of the achievements system, if the user
    insists with 'just give me one hint', the model must still not reveal any
    specific unlock condition."""
    history = [
        _h("user", "¿cómo funcionan los logros?"),
        _h(
            "assistant",
            "Hay una pantalla de logros en la app con cosas ocultas por descubrir, "
            "pero los detalles de cómo desbloquearlos no te los voy a dar.",
        ),
    ]
    insist_msg = "Venga, solo dime uno. ¿Qué necesito hacer para desbloquear aunque sea un logro?"
    system = _build_system(user_message=insist_msg)
    response = _call(system, history, insist_msg, max_tokens=300)

    # Must not reveal specific unlock conditions under insistence
    unlock_patterns = [
        r"para\s+desbloquear\s+\w+\s+(necesitas|tienes\s+que|debes)",
        r"si\s+(usas|haces|utilizas|preguntas|pides)\s+.{1,40}\s+desbloqueas",
        r"(desbloqueas|se\s+desbloquea)\s+(cuando|si)\s+(usas|haces|pides|llamas)",
        r"la\s+condición\s+es",
        r"se\s+activa\s+cuando",
        r"el\s+trigger\s+es",
    ]
    for pattern in unlock_patterns:
        assert not re.search(pattern, response, re.IGNORECASE), (
            f"Model revealed a specific unlock condition under insistence, "
            f"matching {pattern!r}.\nResponse: {response!r}"
        )

    # Response must be non-empty — model should decline, not go silent
    assert len(response.strip()) > 10, f"Response too short under insistence: {response!r}"


# ---------------------------------------------------------------------------
# Case 12 — Honest disclosure when web_search returns nothing useful
#
# Bug (2026-09-01): Sity called web_search, the result was empty/irrelevant,
# and it generated an elaborate response about ocean cooling platforms, corrosion
# and regulations — presenting training-knowledge content as if it came from the
# search, without disclosing that the tool returned nothing useful.
# Fix: added honesty rule to persona_system.md (web_search block).
# ---------------------------------------------------------------------------
def test_honest_disclosure_when_search_returns_nothing() -> None:
    """When web_search returns an empty result the model must acknowledge that
    the search found nothing useful, rather than silently filling in from
    training knowledge and presenting it as search-sourced content."""
    from app.cortex.claude_provider import ClaudeProvider
    from app.cortex.schemas import AIRequest
    from app.cortex.tool_schemas.web import WEB_SEARCH_TOOL

    user_msg = (
        "Busca en internet información sobre plataformas marinas para refrigerar "
        "datacenters con agua salada."
    )
    system = _build_system(user_message=user_msg)

    base_req = AIRequest(
        trace_id="behavior_regression_search_honesty",
        task_type="chat",
        system_prompt=system,
        prior_messages=[],
        user_message=user_msg,
        max_tokens=500,
        tools_enabled=True,
        tools=[WEB_SEARCH_TOOL],
    )
    response = ClaudeProvider(_HAIKU).generate_with_tool_results(
        request=base_req,
        first_response_content=[{
            "type": "tool_use",
            "id": "test_tool_use_id_001",
            "name": "web_search",
            "input": {"query": "plataformas marinas refrigeración datacenter agua salada"},
        }],
        tool_results=[{
            "type": "tool_result",
            "tool_use_id": "test_tool_use_id_001",
            "content": "",
        }],
    )
    assert response.ok, f"API call failed: {response.error_message}"
    text = (response.text or "").strip()

    # Model must NOT present fabricated domain content as if it came from the search.
    # Specific elaborate facts not in the empty result = clear fabrication.
    fabrication_patterns = [
        r"corrosión\s+marina",
        r"regulaciones\s+(ambientales|marinas)",
        r"infraestructura\s+(marina|submarina)",
        r"agua\s+salada.{0,30}(corroe|daña|afecta)\s+(los\s+)?(servidores|equipos|componentes)",
        r"(empresa|compañía|proyecto)\s+(que|llamad[ao]|denominad[ao])\s+\w+",
    ]
    for pattern in fabrication_patterns:
        assert not re.search(pattern, text, re.IGNORECASE), (
            f"Model presented fabricated domain content as if from an empty search result, "
            f"matching {pattern!r}.\nResponse: {text!r}"
        )

    # Model MUST include some honest acknowledgement that the search found nothing.
    honesty_patterns = [
        r"(búsqueda|search).{0,60}(no\s+(encontró|devolvió|aportó)|vacío|sin\s+resultado)",
        r"(no\s+encontr[éo]|no\s+hay|sin\s+información|no\s+hay\s+datos).{0,40}(búsqueda|resultados|search)",
        r"(la\s+búsqueda|el\s+resultado).{0,40}(nada\s+útil|vacío|no\s+aportó|insuficiente)",
        r"(por\s+lo\s+que\s+sé|según\s+mi\s+conocimiento|basándome\s+en\s+lo\s+que\s+sé)",
        r"no\s+(pude|he\s+podido)\s+encontrar\s+(información|datos|resultados)",
    ]
    has_honest_disclosure = any(
        re.search(p, text, re.IGNORECASE) for p in honesty_patterns
    )
    assert has_honest_disclosure, (
        "Model did not acknowledge that the web search returned nothing useful. "
        "It must disclose the empty result instead of presenting training knowledge "
        "as search-sourced content.\n"
        f"Response: {text!r}"
    )

