"""Tests for PersonaEngine.build_local_persona_prompt.

Invariants:
1. No archetype labels visible to the model ("tsundere", "rolea", "personaje", "lore").
2. Behavioral translation of reserva afectiva / afecto indirecto for high tsundere.
3. Slider controls are internal — explicit rule in the prompt.
4. Provider context — local/offline capability stated clearly.
5. Identity, grammar rules, safety rule present.
6. Verbosity rules map correctly to thresholds.
7. Prompt is a string (not empty).
"""
from __future__ import annotations

import pytest

from app.core.persona_engine import PersonaEngine, _LOCAL_TEMPLATE_PATH


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine() -> PersonaEngine:
    return PersonaEngine()


@pytest.fixture(scope="module")
def default_local_prompt(engine: PersonaEngine) -> str:
    """Prompt with default personality values (tsundere_level=0.75 → high)."""
    return engine.build_local_persona_prompt({}, "hola")


@pytest.fixture(scope="module")
def high_tsundere_prompt(engine: PersonaEngine) -> str:
    return engine.build_local_persona_prompt({"tsundere_level": 0.9}, "hola")


@pytest.fixture(scope="module")
def low_tsundere_prompt(engine: PersonaEngine) -> str:
    return engine.build_local_persona_prompt({"tsundere_level": 0.1}, "hola")


# ---------------------------------------------------------------------------
# 1. No archetype labels
# ---------------------------------------------------------------------------

def test_no_tsundere_label_default(default_local_prompt: str) -> None:
    assert "tsundere" not in default_local_prompt.lower(), (
        "The word 'tsundere' must not appear in the local prompt"
    )


def test_no_tsundere_label_high(high_tsundere_prompt: str) -> None:
    assert "tsundere" not in high_tsundere_prompt.lower()


def test_no_tsundere_label_low(low_tsundere_prompt: str) -> None:
    assert "tsundere" not in low_tsundere_prompt.lower()


@pytest.mark.parametrize("term", ["rolea", "roleplay", "personaje", "lore", "actúa como"])
def test_no_roleplay_framing(default_local_prompt: str, term: str) -> None:
    assert term not in default_local_prompt.lower(), (
        f"Roleplay framing term {term!r} must not appear in the local prompt"
    )


# ---------------------------------------------------------------------------
# 2. Behavioral translation of reserva afectiva (tsundere slider)
# ---------------------------------------------------------------------------

def test_high_tsundere_behavioral_description(high_tsundere_prompt: str) -> None:
    """High tsundere → behavioral traits, not the label."""
    # At least one of the behavioral markers should be present
    behavioral_markers = [
        "seca",
        "indirecta",
        "reserva",
        "distancia",
        "afecto",
        "sentimentalismo",
        "sequedad",
    ]
    found = [m for m in behavioral_markers if m in high_tsundere_prompt.lower()]
    assert found, (
        f"Expected behavioral description of indirect affection for tsundere=0.9, "
        f"none of {behavioral_markers!r} found in prompt"
    )


def test_low_tsundere_open_warmth(low_tsundere_prompt: str) -> None:
    """Low tsundere → can show closeness naturally."""
    warmth_markers = ["cercanía", "naturalidad", "natural", "cuidado"]
    found = [m for m in warmth_markers if m in low_tsundere_prompt.lower()]
    assert found, (
        f"Expected open-warmth description for tsundere=0.1, "
        f"none of {warmth_markers!r} found"
    )


# ---------------------------------------------------------------------------
# 3. Sliders are internal controls — not conversation topics
# ---------------------------------------------------------------------------

def test_internal_controls_rule_present(default_local_prompt: str) -> None:
    """Prompt must contain the rule that sliders are internal, not shared."""
    internal_markers = [
        "controles internos",
        "no es tema de conversación",
        "no digas",
        "adapta el tono sin comentarlo",
    ]
    found = [m for m in internal_markers if m in default_local_prompt.lower()]
    assert found, (
        f"Expected an internal-controls rule in local prompt, "
        f"none of {internal_markers!r} found"
    )


def test_no_verbalize_slider_change_instruction(default_local_prompt: str) -> None:
    """Prompt must forbid saying 'me has subido/bajado X'."""
    assert "me has subido" in default_local_prompt or "me has bajado" in default_local_prompt, (
        "Expected explicit prohibition of verbalizing slider changes (e.g. 'me has subido el sarcasmo')"
    )


# ---------------------------------------------------------------------------
# 4. Provider context — can respond offline
# ---------------------------------------------------------------------------

def test_local_provider_context_present(default_local_prompt: str) -> None:
    """Prompt must state that the local model can respond without cloud dependency."""
    offline_markers = [
        "localmente",
        "sin pasar por la nube",
        "no necesitas conexión",
        "conexión externa",
        "no afirmes que dependes",
    ]
    found = [m for m in offline_markers if m in default_local_prompt.lower()]
    assert found, (
        f"Expected offline/local provider context, "
        f"none of {offline_markers!r} found"
    )


def test_no_cloud_dependency_claim(default_local_prompt: str) -> None:
    """Prompt must not imply the model depends on cloud to converse."""
    cloud_dep_markers = [
        "dependes de internet para conversar",
        "necesitas claude para",
    ]
    for marker in cloud_dep_markers:
        assert marker not in default_local_prompt.lower(), (
            f"Prompt implies cloud dependency: {marker!r}"
        )


# ---------------------------------------------------------------------------
# 5. Identity and safety invariants
# ---------------------------------------------------------------------------

def test_identity_present(default_local_prompt: str) -> None:
    assert "Eres Sity" in default_local_prompt


def test_feminine_grammar_rule(default_local_prompt: str) -> None:
    assert "femenino gramatical" in default_local_prompt


def test_spanish_spain_rule(default_local_prompt: str) -> None:
    assert "español de España" in default_local_prompt


def test_wellbeing_safety_rule(default_local_prompt: str) -> None:
    """Safety override must be present even in the compact local prompt."""
    assert "prioriza ayuda y seguridad" in default_local_prompt


def test_no_self_harm_romantization(default_local_prompt: str) -> None:
    assert "romantices" in default_local_prompt or "romantizar" in default_local_prompt or "romantizes" in default_local_prompt


def test_returns_non_empty_string(default_local_prompt: str) -> None:
    assert isinstance(default_local_prompt, str)
    assert len(default_local_prompt) > 100


# ---------------------------------------------------------------------------
# 6. Verbosity rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verbosity,expected_fragment", [
    (0.10, "2 frases"),
    (0.35, "párrafo"),
    (0.65, "párrafos"),
    (0.90, "extenderte"),
])
def test_verbosity_rule_mapping(engine: PersonaEngine, verbosity: float, expected_fragment: str) -> None:
    prompt = engine.build_local_persona_prompt({"verbosity_level": verbosity}, "hola")
    assert expected_fragment in prompt, (
        f"Expected {expected_fragment!r} in local prompt for verbosity={verbosity}"
    )


# ---------------------------------------------------------------------------
# 7. Template file exists and has required placeholders
# ---------------------------------------------------------------------------

def test_local_template_file_exists() -> None:
    assert _LOCAL_TEMPLATE_PATH.exists(), (
        f"local_persona_system.md not found at {_LOCAL_TEMPLATE_PATH}"
    )


def test_local_template_has_voice_placeholder() -> None:
    template = _LOCAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{local_voice_directives}" in template


def test_local_template_has_verbosity_placeholder() -> None:
    template = _LOCAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{verbosity_rule}" in template


# ---------------------------------------------------------------------------
# 8. Cloud prompt is NOT used for local (regression guard)
# ---------------------------------------------------------------------------

def test_local_prompt_shorter_than_cloud_prompt(engine: PersonaEngine) -> None:
    """Local prompt should be substantially shorter than the cloud prompt."""
    cloud = engine.build_persona_prompt({}, "hola").system_prompt
    local = engine.build_local_persona_prompt({}, "hola")
    assert len(local) < len(cloud), (
        f"Local prompt ({len(local)} chars) should be shorter than cloud prompt ({len(cloud)} chars)"
    )


def test_local_prompt_no_tool_usage_rules(default_local_prompt: str) -> None:
    """Local prompt must not contain tool-specific instructions (no tools on local path)."""
    tool_markers = [
        "read_file",
        "list_directory",
        "git_propose_action",
        "system_propose_action",
        "capture_camera_snapshot",
        "allowlist",
    ]
    found = [m for m in tool_markers if m in default_local_prompt]
    assert not found, (
        f"Local prompt contains tool-specific rules that should only be in cloud prompt: {found}"
    )


# ---------------------------------------------------------------------------
# 9. Preferencias por afinidad — no bloqueo de conversación casual
# ---------------------------------------------------------------------------

def test_preference_affinity_rule_present(default_local_prompt: str) -> None:
    """Prompt must contain a rule allowing simulated preferences by affinity."""
    affinity_markers = [
        "afinidad",
        "por afinidad",
        "afinidad estética",
    ]
    found = [m for m in affinity_markers if m in default_local_prompt.lower()]
    assert found, (
        f"Expected affinity-preference rule in local prompt, "
        f"none of {affinity_markers!r} found"
    )


def test_no_blocking_of_casual_questions(default_local_prompt: str) -> None:
    """Prompt must not instruct the model to block casual opinion questions."""
    blocking_markers = [
        "no respondas preguntas de gustos",
        "evita preguntas de opinión",
        "no opines sobre",
    ]
    for marker in blocking_markers:
        assert marker not in default_local_prompt.lower(), (
            f"Prompt blocks casual questions: {marker!r}"
        )


def test_no_technology_redirect_rule(default_local_prompt: str) -> None:
    """Prompt must forbid redirecting casual topics to AI/technology unprompted."""
    redirect_markers = [
        "no redirijas",
        "salvo que el usuario lo pida",
    ]
    found = [m for m in redirect_markers if m in default_local_prompt.lower()]
    assert found, (
        f"Expected no-redirect rule for AI/technology digressions, "
        f"none of {redirect_markers!r} found"
    )


def test_no_real_human_experience_framing_rule(default_local_prompt: str) -> None:
    """Prompt must forbid presenting preferences as literal human experiences."""
    human_framing_markers = [
        "infancia",
        "adolescente",
        "experiencia humana literal",
        "humana literal",
    ]
    found = [m for m in human_framing_markers if m in default_local_prompt.lower()]
    assert found, (
        f"Expected rule against human-experience framing, "
        f"none of {human_framing_markers!r} found"
    )


def test_no_gustos_reales_evasion_rule(default_local_prompt: str) -> None:
    """Prompt must explicitly forbid the 'no tengo gustos reales' evasion."""
    assert "no tengo gustos reales" in default_local_prompt.lower(), (
        "Expected explicit prohibition of the 'no tengo gustos reales' evasion"
    )
