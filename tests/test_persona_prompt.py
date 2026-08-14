from __future__ import annotations

import pytest

from app.core.persona_engine import PersonaEngine, _TEMPLATE_PATH, _REFUSAL_ACTIVE
from app.settings.settings_service import CANONICAL_PERSONALITY


@pytest.fixture(scope="module")
def engine() -> PersonaEngine:
    return PersonaEngine()


@pytest.fixture(scope="module")
def default_prompt(engine: PersonaEngine) -> str:
    return engine.build_persona_prompt({}, "hola").system_prompt


@pytest.fixture(scope="module")
def template_source() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# 1. Prompt content invariants                                         #
# ------------------------------------------------------------------ #

def test_identity_in_prompt(default_prompt: str) -> None:
    assert "Eres Sity" in default_prompt


@pytest.mark.parametrize("fragment", [
    "femenino gramatical",
    "Estoy lista",
    "Me siento vacía",
    "Estoy listo",
    "Me siento vacío",
])
def test_grammar_rule_in_prompt(default_prompt: str, fragment: str) -> None:
    assert fragment in default_prompt, f"Missing grammar fragment: {fragment!r}"


def test_wellbeing_rule_in_prompt(default_prompt: str) -> None:
    assert "No romantices autolesiones" in default_prompt


def test_safety_override_in_prompt(default_prompt: str) -> None:
    assert "prioriza ayuda y seguridad" in default_prompt


def test_refusal_mode_concept_in_prompt(default_prompt: str) -> None:
    assert "refusal_mode" in default_prompt


@pytest.mark.parametrize("marker", [
    "<function_calls>",
    "<invoke ",
    "<attempt_tool_use>",
])
def test_no_pseudo_tool_calls_in_prompt(default_prompt: str, marker: str) -> None:
    assert marker not in default_prompt, f"Prompt contains pseudo-tool-call marker: {marker!r}"


# ------------------------------------------------------------------ #
# 2. Template source: no hardcoded paths or service names             #
# ------------------------------------------------------------------ #

def test_template_no_hardcoded_path(template_source: str) -> None:
    assert "/home/alex/projects/sity" not in template_source, (
        "persona_system.md contains hardcoded personal path — use {project_root}"
    )


def test_template_no_hardcoded_service(template_source: str) -> None:
    assert "sity-backend" not in template_source, (
        "persona_system.md contains hardcoded service name — use {allowed_systemd_services}"
    )


# ------------------------------------------------------------------ #
# 3. _should_refuse — deterministic paths                             #
# ------------------------------------------------------------------ #

def test_order_override_blocks_refusal(engine: PersonaEngine) -> None:
    assert not engine._should_refuse("es una orden hazlo", 1.0)


def test_refusal_chance_zero_never_refuses(engine: PersonaEngine) -> None:
    assert not engine._should_refuse("cuéntame algo trivial", 0.0)


def test_refusal_chance_one_always_refuses(engine: PersonaEngine) -> None:
    assert engine._should_refuse("cuéntame algo trivial", 1.0)


def test_refusal_chance_one_always_refuses_on_any_message(engine: PersonaEngine) -> None:
    # _should_refuse is purely probabilistic — the model decides about trivial messages
    # via the natural language instruction in _REFUSAL_ACTIVE, not via Python logic.
    assert engine._should_refuse("Hola", 1.0)
    assert engine._should_refuse("Ok", 1.0)


# ------------------------------------------------------------------ #
# 4. build_persona_prompt — refusal_mode_override                     #
# ------------------------------------------------------------------ #

def test_refusal_override_true(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({}, "hola", refusal_mode_override=True)
    assert result.refusal_mode is True
    assert "refusal_mode está ACTIVADO" in result.system_prompt
    # Must NOT give the model opt-out discretion over refusal itself.
    assert "Esta decisión es tuya" not in result.system_prompt
    assert "si quieres aplicarlo" not in result.system_prompt


def test_refusal_override_false_suppresses_refusal(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt(
        {"refusal_chance": 1.0}, "hola trivial", refusal_mode_override=False
    )
    assert result.refusal_mode is False
    assert "refusal_mode está DESACTIVADO" in result.system_prompt


def test_refusal_override_none_delegates_to_should_refuse_true(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"refusal_chance": 1.0}, "cuéntame algo trivial")
    assert result.refusal_mode is True


def test_refusal_override_none_delegates_to_should_refuse_false(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"refusal_chance": 0.0}, "hola")
    assert result.refusal_mode is False


def test_refusal_chance_one_always_activates(engine: PersonaEngine) -> None:
    """refusal_chance=1.0 must always produce refusal_mode=True — deterministic."""
    for _ in range(20):
        result = engine.build_persona_prompt({"refusal_chance": 1.0}, "dime algo trivial")
        assert result.refusal_mode is True


def test_refusal_chance_zero_never_activates(engine: PersonaEngine) -> None:
    """refusal_chance=0.0 must always produce refusal_mode=False — deterministic."""
    for _ in range(20):
        result = engine.build_persona_prompt({"refusal_chance": 0.0}, "hola")
        assert result.refusal_mode is False


def test_refusal_chance_half_is_probabilistic(engine: PersonaEngine) -> None:
    """refusal_chance=0.5 should produce ~50% True over many trials."""
    results = [
        engine.build_persona_prompt({"refusal_chance": 0.5}, "dime algo").refusal_mode
        for _ in range(1000)
    ]
    ratio = sum(results) / len(results)
    assert 0.40 <= ratio <= 0.60, f"Expected ~0.5 ratio, got {ratio:.3f}"


def test_refusal_active_prompt_is_unconditional(engine: PersonaEngine) -> None:
    """When refusal_mode=True, the prompt must not give the model opt-out discretion."""
    result = engine.build_persona_prompt({}, "hola", refusal_mode_override=True)
    prompt = result.system_prompt
    assert "ACTIVADO" in prompt
    assert "Esta decisión es tuya" not in prompt
    assert "no obligatorio" not in prompt
    assert "si quieres aplicarlo" not in prompt


def test_refusal_active_backend_verified(engine: PersonaEngine) -> None:
    """_REFUSAL_ACTIVE must state the backend already verified the message is real."""
    assert "verificó" in _REFUSAL_ACTIVE or "verificado" in _REFUSAL_ACTIVE.lower()
    assert "petición real" in _REFUSAL_ACTIVE.lower()


def test_refusal_active_has_no_invent_data_rule(engine: PersonaEngine) -> None:
    """_REFUSAL_ACTIVE must explicitly prohibit inventing false data."""
    assert "nunca inventes" in _REFUSAL_ACTIVE.lower()
    assert "dato" in _REFUSAL_ACTIVE
    assert "número" in _REFUSAL_ACTIVE or "numero" in _REFUSAL_ACTIVE
    assert "configuración" in _REFUSAL_ACTIVE or "configuracion" in _REFUSAL_ACTIVE


# ------------------------------------------------------------------ #
# 5. PersonaDecision structure                                         #
# ------------------------------------------------------------------ #

def test_persona_decision_system_prompt_is_str(engine: PersonaEngine) -> None:
    decision = engine.build_persona_prompt({}, "hola")
    assert isinstance(decision.system_prompt, str)


def test_persona_decision_system_prompt_non_trivial(engine: PersonaEngine) -> None:
    decision = engine.build_persona_prompt({}, "hola")
    assert len(decision.system_prompt) > 200


def test_persona_decision_refusal_mode_is_bool(engine: PersonaEngine) -> None:
    decision = engine.build_persona_prompt({}, "hola")
    assert isinstance(decision.refusal_mode, bool)


# ------------------------------------------------------------------ #
# 6. Idioma e interlocutor — tuteo singular, no voseo, no vosotros   #
# ------------------------------------------------------------------ #

def test_interlocutor_alex_in_prompt(default_prompt: str) -> None:
    assert "Alex" in default_prompt, "Prompt must name Alex as the sole interlocutor"


def test_tuteo_singular_section_in_prompt(default_prompt: str) -> None:
    assert "segunda persona del singular" in default_prompt or "tuteo" in default_prompt


@pytest.mark.parametrize("form", ["tú", "quieres", "puedes", "tienes"])
def test_tuteo_forms_in_prompt(default_prompt: str, form: str) -> None:
    assert form in default_prompt, f"Tuteo form {form!r} must appear in prompt"


@pytest.mark.parametrize("voseo", ["vos", "querés", "tenés", "podés", "hacés", "sos"])
def test_voseo_forms_listed_in_prompt(default_prompt: str, voseo: str) -> None:
    # Each forbidden voseo form must appear verbatim in the no-voseo prohibition rule.
    assert voseo in default_prompt, f"Voseo form {voseo!r} must be explicitly listed in the no-voseo rule"


@pytest.mark.parametrize("plural", ["vosotros", "vosotras", "vuestro", "estáis", "hacéis", "queréis"])
def test_plural_forms_listed_in_prompt(default_prompt: str, plural: str) -> None:
    # Each forbidden plural form must appear verbatim in the no-plural prohibition rule.
    assert plural in default_prompt, f"Plural form {plural!r} must be explicitly listed in the no-plural rule"


def test_no_voseo_rule_present(default_prompt: str) -> None:
    assert "voseo" in default_prompt, "Prompt must contain an explicit no-voseo rule"


def test_no_vosotros_rule_present(default_prompt: str) -> None:
    assert "vosotros" in default_prompt, "Prompt must contain an explicit no-vosotros rule"


# ------------------------------------------------------------------ #
# 7. _build_style_directives — verbosity ranges                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("verbosity,expected_fragment", [
    (0.0,  "máximo 2 frases"),        # very_low (≤0.20)
    (0.2,  "máximo 2 frases"),        # very_low (≤0.20)
    (0.35, "Verbosidad baja"),        # low (0.20<x≤0.40)
    (0.5,  "longitud de la respuesta depende del contenido"),  # mid (0.40<x≤0.60)
    (0.79, "Verbosidad alta"),        # high (0.60<x≤0.80)
    (0.8,  "Verbosidad alta"),        # high (≤0.80)
    (1.0,  "Verbosidad alta"),        # very_high — "Verbosidad muy alta" contains "Verbosidad alta"
])
def test_verbosity_directive_ranges_admin(engine: PersonaEngine, verbosity: float, expected_fragment: str) -> None:
    """Admin sessions use full verbosity range — no cap applied."""
    result = engine.build_persona_prompt({"verbosity_level": verbosity}, "hola", is_admin=True)
    assert expected_fragment in result.system_prompt, (
        f"Expected {expected_fragment!r} in prompt for verbosity={verbosity} (admin)"
    )


@pytest.mark.parametrize("verbosity,expected_fragment", [
    (0.0,  "máximo 2 frases"),    # below cap
    (0.15, "máximo 2 frases"),    # at cap
    (0.35, "máximo 2 frases"),    # above cap — clamped to 0.15
    (1.0,  "máximo 2 frases"),    # slider max — still clamped
])
def test_verbosity_directive_ranges_non_admin(engine: PersonaEngine, verbosity: float, expected_fragment: str) -> None:
    """Non-admin sessions cap effective verbosity at 0.15 → always band 1."""
    result = engine.build_persona_prompt({"verbosity_level": verbosity}, "hola", is_admin=False)
    assert expected_fragment in result.system_prompt, (
        f"Expected {expected_fragment!r} in prompt for verbosity={verbosity} (non-admin)"
    )


# ------------------------------------------------------------------ #
# 8. _build_style_directives — skepticism ranges                      #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("skepticism,expected_fragment", [
    # Texts unique to the dynamic directive (not in the static template interpretation section)
    (0.0,  "beneficio de la duda por defecto"),    # very_low
    (0.2,  "beneficio de la duda por defecto"),    # very_low (≤0.20)
    (0.8,  "cuestiona activamente"),               # high (≤0.80)
    (1.0,  "cuestiona sistemáticamente"),          # very_high (>0.80)
])
def test_skepticism_directive_ranges(engine: PersonaEngine, skepticism: float, expected_fragment: str) -> None:
    result = engine.build_persona_prompt({"skepticism_level": skepticism}, "hola")
    assert expected_fragment in result.system_prompt, (
        f"Expected {expected_fragment!r} in prompt for skepticism={skepticism}"
    )


def test_skepticism_mid_range_moderate_directive(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"skepticism_level": 0.5}, "hola")
    assert "cuestiona activamente" not in result.system_prompt
    assert "beneficio de la duda por defecto" not in result.system_prompt
    assert "moderado" in result.system_prompt or "sentido común" in result.system_prompt


# ------------------------------------------------------------------ #
# 9. 5-level directive system — all params produce distinct content   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("param,very_low_fragment,very_high_fragment", [
    ("sarcasm_level",           "Sarcasmo muy bajo",          "Sarcasmo muy alto"),
    ("rudeness_level",          "Mala leche muy baja",        "Mala leche muy alta"),
    ("warmth_level",            "Calidez muy baja",           "Calidez muy alta"),
    ("honesty_level",           "Honestidad muy baja",        "Honestidad muy alta"),
    ("initiative_level",        "Iniciativa muy baja",        "Iniciativa muy alta"),
    ("dry_humor_level",         "Humor seco muy bajo",        "Humor seco muy alto"),
    ("frialdad_afectiva_level", "Frialdad afectiva muy baja", "Frialdad afectiva muy alta"),
    ("contrarian_level",        "Contradicción muy baja",     "Contradicción muy alta"),
    ("patience_level",          "Paciencia muy baja",         "Paciencia muy alta"),
    ("helpfulness_level",       "Ayuda muy baja",             "Ayuda muy alta"),
    ("verbosity_level",         "máximo 2 frases",            "Verbosidad muy alta"),
    ("melancholy_level",        "Melancolía muy baja",        "Melancolía muy alta"),
    ("skepticism_level",        "Escepticismo muy bajo",      "Escepticismo muy alto"),
])
def test_five_level_directive_extremes(
    engine: PersonaEngine, param: str, very_low_fragment: str, very_high_fragment: str
) -> None:
    """Each parameter injects distinct directive text at very_low (0.0) and very_high (1.0).
    Admin sessions used here to bypass verbosity cap and test full range for verbosity_level."""
    low_result = engine.build_persona_prompt({param: 0.0}, "hola", is_admin=True)
    high_result = engine.build_persona_prompt({param: 1.0}, "hola", is_admin=True)
    assert very_low_fragment in low_result.system_prompt, (
        f"Expected {very_low_fragment!r} for {param}=0.0"
    )
    assert very_high_fragment in high_result.system_prompt, (
        f"Expected {very_high_fragment!r} for {param}=1.0"
    )


def test_refusal_high_directive_injected(engine: PersonaEngine) -> None:
    """refusal_chance ≥ 0.80 injects a Negativa directive; low values do not."""
    high = engine.build_persona_prompt({"refusal_chance": 1.0}, "hola")
    assert "Negativa" in high.system_prompt
    low = engine.build_persona_prompt({"refusal_chance": 0.0}, "hola")
    assert "Negativa muy alta" not in low.system_prompt
    assert "Negativa alta" not in low.system_prompt


# ------------------------------------------------------------------ #
# 10. CANONICAL_PERSONALITY completeness                              #
# ------------------------------------------------------------------ #

def test_canonical_personality_includes_skepticism() -> None:
    assert "skepticism_level" in CANONICAL_PERSONALITY, (
        "skepticism_level missing from CANONICAL_PERSONALITY — restore defaults will not apply it"
    )
    assert CANONICAL_PERSONALITY["skepticism_level"] == 0.2


# ------------------------------------------------------------------ #
# 11. Idioma de conversación — language_override                      #
# ------------------------------------------------------------------ #

def test_default_language_auto_detects(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola").system_prompt
    assert "Detecta el idioma" in prompt


def test_language_override_es_es(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="es-ES").system_prompt
    assert "castellano de España" in prompt


def test_language_override_en_us(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="en-US").system_prompt
    assert "American English" in prompt

def test_language_override_ja(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="ja").system_prompt
    assert "日本語" in prompt


def test_language_override_unknown_falls_back_to_auto(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="xx-XX").system_prompt
    assert "Detecta el idioma" in prompt


def test_default_prompt_no_hardcoded_spanish(default_prompt: str) -> None:
    assert "Responde siempre en castellano de España" not in default_prompt, (
        "Default (auto) prompt must not hardcode Spanish — language is dynamic"
    )


# ------------------------------------------------------------------ #
# 12. Verbosity cap — User/Guest vs Admin                             #
# ------------------------------------------------------------------ #

def test_verbosity_cap_non_admin_clamps_to_lowest_band(engine: PersonaEngine) -> None:
    """User/Guest with verbosity=1.0 should get lowest verbosity directive (cap at 0.15)."""
    result = engine.build_persona_prompt({"verbosity_level": 1.0}, "hola", is_admin=False)
    assert "máximo 2 frases" in result.system_prompt, (
        "Non-admin with verbosity=1.0 must be capped to band 1 (≤0.20 → 'máximo 2 frases')"
    )


def test_verbosity_cap_admin_full_range(engine: PersonaEngine) -> None:
    """Admin with verbosity=1.0 should get highest verbosity directive (no cap)."""
    result = engine.build_persona_prompt({"verbosity_level": 1.0}, "hola", is_admin=True)
    assert "Verbosidad muy alta" in result.system_prompt, (
        "Admin with verbosity=1.0 must get highest-band directive — full range applies"
    )


def test_verbosity_cap_non_admin_mid_verbosity(engine: PersonaEngine) -> None:
    """Non-admin with verbosity=0.50 (above cap) → same band as 0.15."""
    result = engine.build_persona_prompt({"verbosity_level": 0.50}, "hola", is_admin=False)
    assert "máximo 2 frases" in result.system_prompt


def test_verbosity_cap_does_not_affect_other_params(engine: PersonaEngine) -> None:
    """Verbosity cap must not bleed into other personality parameters."""
    result = engine.build_persona_prompt(
        {"verbosity_level": 1.0, "sarcasm_level": 1.0}, "hola", is_admin=False
    )
    # Sarcasm should still be at max despite verbosity being capped
    assert "Sarcasmo muy alto" in result.system_prompt
