from __future__ import annotations

import pytest

from app.core.persona_engine import CRITICAL_KEYWORDS, PersonaEngine, _TEMPLATE_PATH


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
    "español de España",
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

@pytest.mark.parametrize("kw", ["seguridad", "debug", "logs", "configuración", "personalidad", "error"])
def test_spot_critical_keywords_block_refusal(engine: PersonaEngine, kw: str) -> None:
    assert not engine._should_refuse(kw, 1.0), f"Critical keyword {kw!r} must block refusal_mode"


@pytest.mark.parametrize("kw", sorted(CRITICAL_KEYWORDS))
def test_all_critical_keywords_block_refusal(engine: PersonaEngine, kw: str) -> None:
    assert not engine._should_refuse(kw, 1.0), f"CRITICAL_KEYWORD {kw!r} must block refusal_mode"


def test_order_override_blocks_refusal(engine: PersonaEngine) -> None:
    assert not engine._should_refuse("es una orden hazlo", 1.0)


def test_refusal_chance_zero_never_refuses(engine: PersonaEngine) -> None:
    assert not engine._should_refuse("cuéntame algo trivial", 0.0)


def test_refusal_chance_one_always_refuses(engine: PersonaEngine) -> None:
    assert engine._should_refuse("cuéntame algo trivial", 1.0)


# ------------------------------------------------------------------ #
# 4. build_persona_prompt — refusal_mode_override                     #
# ------------------------------------------------------------------ #

def test_refusal_override_true(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({}, "hola", refusal_mode_override=True)
    assert result.refusal_mode is True
    assert "refusal_mode=true" in result.system_prompt


def test_refusal_override_false_suppresses_refusal(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt(
        {"refusal_chance": 1.0}, "hola trivial", refusal_mode_override=False
    )
    assert result.refusal_mode is False
    assert "refusal_mode=false" in result.system_prompt


def test_refusal_override_none_delegates_to_should_refuse_true(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"refusal_chance": 1.0}, "cuéntame algo trivial")
    assert result.refusal_mode is True


def test_refusal_override_none_delegates_to_should_refuse_false(engine: PersonaEngine) -> None:
    result = engine.build_persona_prompt({"refusal_chance": 0.0}, "hola")
    assert result.refusal_mode is False


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
