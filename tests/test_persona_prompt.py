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
    result = engine.build_persona_prompt({}, "hola trivial", refusal_mode_override=False)
    assert result.refusal_mode is False
    assert "refusal_mode está DESACTIVADO" in result.system_prompt


def test_refusal_override_none_uses_derived_propensity_zero(engine: PersonaEngine) -> None:
    # helpfulness=1.0, assertiveness=0.0, independence=0.0 →
    # propensity = 0.20*0 + 0.15*0 - 0.40*1.0 + 0.20 = -0.20 → clamped to 0 → never refuses
    traits = {"helpfulness": 1.0, "assertiveness": 0.0, "independence": 0.0}
    result = engine.build_persona_prompt(traits, "cuéntame algo")
    assert result.refusal_mode is False


def test_refusal_override_true_always_activates(engine: PersonaEngine) -> None:
    """refusal_mode_override=True must always produce refusal_mode=True — deterministic."""
    for _ in range(20):
        result = engine.build_persona_prompt({}, "dime algo trivial", refusal_mode_override=True)
        assert result.refusal_mode is True


def test_refusal_override_false_never_activates(engine: PersonaEngine) -> None:
    """refusal_mode_override=False must always produce refusal_mode=False — deterministic."""
    for _ in range(20):
        result = engine.build_persona_prompt({}, "hola", refusal_mode_override=False)
        assert result.refusal_mode is False


def test_refusal_propensity_probabilistic_from_traits(engine: PersonaEngine) -> None:
    """Traits that give ~50% propensity produce ~50% refusal_mode over many trials.
    Formula: 0.20*assertiveness + 0.15*independence - 0.40*helpfulness + 0.20
    With assertiveness=1.0, independence=1.0, helpfulness=0.125: propensity = 0.50
    """
    traits = {"assertiveness": 1.0, "independence": 1.0, "helpfulness": 0.125}
    results = [
        engine.build_persona_prompt(traits, "dime algo").refusal_mode
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
    result = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": verbosity}, is_admin=True)
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
    result = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": verbosity}, is_admin=False)
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
    result = engine.build_persona_prompt({"skepticism": skepticism}, "hola")
    assert expected_fragment in result.system_prompt, (
        f"Expected {expected_fragment!r} in prompt for skepticism={skepticism}"
    )


def test_skepticism_mid_range_moderate_directive(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"skepticism": 0.5}, "hola")
    assert "cuestiona activamente" not in result.system_prompt
    assert "beneficio de la duda por defecto" not in result.system_prompt
    assert "moderado" in result.system_prompt or "sentido común" in result.system_prompt


# ------------------------------------------------------------------ #
# 9. 5-level directive system — all params produce distinct content   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("param,very_low_fragment,very_high_fragment", [
    ("warmth",              "Calidez muy baja",              "Calidez muy alta"),
    ("empathy",             "Empatía muy baja",              "Empatía muy alta"),
    ("directness",          "Directness muy baja",           "Directness muy alta"),
    ("assertiveness",       "Assertiveness muy baja",        "Assertiveness muy alta"),
    ("independence",        "Independencia muy baja",        "Independencia muy alta"),
    ("skepticism",          "Escepticismo muy bajo",         "Escepticismo muy alto"),
    ("patience",            "Paciencia muy baja",            "Paciencia muy alta"),
    ("curiosity",           "Curiosidad muy baja",           "Curiosidad muy alta"),
    ("proactivity",         "Proactividad muy baja",         "Proactividad muy alta"),
    ("helpfulness",         "Ayuda muy baja",                "Ayuda muy alta"),
    ("honesty",             "Honestidad muy baja",           "Honestidad muy alta"),
    ("playfulness",         "Playfulness muy baja",          "Playfulness muy alta"),
    ("emotional_stability", "Estabilidad emocional muy baja","Estabilidad emocional muy alta"),
])
def test_five_level_directive_extremes(
    engine: PersonaEngine, param: str, very_low_fragment: str, very_high_fragment: str
) -> None:
    """Each of the 13 personality traits injects distinct directive text at 0.0 and 1.0."""
    low_result = engine.build_persona_prompt({param: 0.0}, "hola", is_admin=True)
    high_result = engine.build_persona_prompt({param: 1.0}, "hola", is_admin=True)
    assert very_low_fragment in low_result.system_prompt, (
        f"Expected {very_low_fragment!r} for {param}=0.0"
    )
    assert very_high_fragment in high_result.system_prompt, (
        f"Expected {very_high_fragment!r} for {param}=1.0"
    )


def test_verbosity_extremes_via_comm_prefs(engine: PersonaEngine) -> None:
    """Verbosity lives in comm_prefs; test extreme directives there."""
    low = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": 0.0}, is_admin=True)
    high = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": 1.0}, is_admin=True)
    assert "máximo 2 frases" in low.system_prompt
    assert "Verbosidad muy alta" in high.system_prompt


def test_melancholy_extremes_via_mental_state(engine: PersonaEngine) -> None:
    """Melancholy lives in mental_state; test extreme directives there."""
    low = engine.build_persona_prompt({}, "hola", mental_state={"melancholy": 0.0})
    high = engine.build_persona_prompt({}, "hola", mental_state={"melancholy": 1.0})
    assert "Melancolía muy baja" in low.system_prompt
    assert "Melancolía muy alta" in high.system_prompt


# ------------------------------------------------------------------ #
# 10. CANONICAL_PERSONALITY completeness                              #
# ------------------------------------------------------------------ #

def test_canonical_personality_includes_skepticism() -> None:
    assert "skepticism" in CANONICAL_PERSONALITY, (
        "skepticism missing from CANONICAL_PERSONALITY — restore defaults will not apply it"
    )
    assert CANONICAL_PERSONALITY["skepticism"] == pytest.approx(0.80)


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
# 11b. Drift de registro — es-ES tuteo fijo ante historial con voseo  #
# ------------------------------------------------------------------ #

def test_es_es_language_block_contains_tuteo_forms(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="es-ES").system_prompt
    for form in ("tú", "quieres", "puedes", "tienes"):
        assert form in prompt, f"es-ES language block must include tuteo form {form!r}"


def test_es_es_language_block_bans_voseo_forms(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="es-ES").system_prompt
    for form in ("vos", "querés", "tenés", "podés", "hacés", "sos"):
        assert form in prompt, f"es-ES language block must list forbidden voseo form {form!r}"


def test_es_es_language_block_anchors_register_for_drift(engine: PersonaEngine) -> None:
    prompt = engine.build_persona_prompt({}, "hola", language_override="es-ES").system_prompt
    assert "historial es información" in prompt, (
        "es-ES language block must state that history is information, not a style directive"
    )


def test_history_rule_references_active_language_block(default_prompt: str) -> None:
    assert "REGLA DE IDIOMA activa" in default_prompt, (
        "History anti-drift rule must anchor register to the active REGLA DE IDIOMA, not hardcode a dialect"
    )


def test_es_es_voseo_forms_appear_in_language_block_not_only_static(engine: PersonaEngine) -> None:
    prompt_es = engine.build_persona_prompt({}, "hola", language_override="es-ES").system_prompt
    prompt_ja = engine.build_persona_prompt({}, "hola", language_override="ja").system_prompt
    for form in ("vos", "querés", "tenés"):
        assert form in prompt_es, f"es-ES prompt must ban voseo form {form!r}"
        # ja prompt still has the static anti-voseo section (it's always in the template)
        # but NOT in the language block — verify the static section covers it
        assert form in prompt_ja, f"Static anti-voseo rule must be present for all languages too"


def test_other_language_blocks_unaffected_by_es_es_fix(engine: PersonaEngine) -> None:
    for lang, expected in [
        ("en-US", "American English"),
        ("en-GB", "British English"),
        ("pt-BR", "português brasileiro"),
        ("fr-FR", "français"),
        ("ja",    "日本語"),
    ]:
        prompt = engine.build_persona_prompt({}, "hola", language_override=lang).system_prompt
        assert expected in prompt, f"language_override={lang!r} must contain {expected!r}"
        assert "tuteo" not in prompt or "español" in prompt.lower(), (
            f"Non-Spanish language block ({lang}) must not inject tuteo as an active rule — "
            "it can only appear in the shared static anti-voseo section"
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
    result = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": 1.0}, is_admin=True)
    assert "Verbosidad muy alta" in result.system_prompt, (
        "Admin with verbosity=1.0 must get highest-band directive — full range applies"
    )


def test_verbosity_cap_non_admin_mid_verbosity(engine: PersonaEngine) -> None:
    """Non-admin with verbosity=0.50 (above cap) → same band as 0.15."""
    result = engine.build_persona_prompt({}, "hola", comm_prefs={"verbosity": 0.50}, is_admin=False)
    assert "máximo 2 frases" in result.system_prompt


def test_verbosity_cap_does_not_affect_other_params(engine: PersonaEngine) -> None:
    """Verbosity cap must not bleed into other personality parameters."""
    result = engine.build_persona_prompt(
        {"playfulness": 1.0}, "hola", comm_prefs={"verbosity": 1.0}, is_admin=False
    )
    # Playfulness should still be at max despite verbosity being capped
    assert "Playfulness muy alta" in result.system_prompt
