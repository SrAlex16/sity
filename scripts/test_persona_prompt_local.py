#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from app.core.persona_engine import CRITICAL_KEYWORDS, PersonaEngine  # noqa: E402

    engine = PersonaEngine()

    # ------------------------------------------------------------------ #
    # 1. Prompt content invariants (default personality, non-refusal turn) #
    # ------------------------------------------------------------------ #
    prompt = engine.build_persona_prompt({}, "hola").system_prompt

    # Identidad
    assert "Eres Sity" in prompt, "Missing identity statement"

    # Regla gramatical de género
    for fragment in [
        "femenino gramatical",
        "español de España",
        "Estoy lista",      # ejemplo correcto
        "Me siento vacía",  # ejemplo correcto
        "Estoy listo",      # ejemplo de forma incorrecta
        "Me siento vacío",  # ejemplo de forma incorrecta
    ]:
        assert fragment in prompt, f"Missing grammar fragment: {fragment!r}"

    # Bienestar / seguridad
    assert "No romantices autolesiones" in prompt, "Missing wellbeing rule"
    assert "prioriza ayuda y seguridad" in prompt, "Missing safety override rule"

    # Concepto de refusal_mode
    assert "refusal_mode" in prompt, "Missing refusal_mode concept"

    # Sin pseudo-tool-calls en el prompt
    for marker in ["<function_calls>", "<invoke ", "<attempt_tool_use>"]:
        assert marker not in prompt, f"Prompt contains pseudo-tool-call marker: {marker!r}"

    # ------------------------------------------------------------------ #
    # 2. Template source checks (no hardcoded paths or service names)      #
    # ------------------------------------------------------------------ #
    from app.core.persona_engine import _TEMPLATE_PATH  # noqa: E402

    template_source = _TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "/home/alex/projects/sity" not in template_source, (
        "persona_system.md contains hardcoded personal path — use {project_root} placeholder"
    )
    assert "sity-backend" not in template_source, (
        "persona_system.md contains hardcoded service name — use {allowed_systemd_services} placeholder"
    )

    # ------------------------------------------------------------------ #
    # 3. _should_refuse — deterministic paths                              #
    # ------------------------------------------------------------------ #

    # critical keywords block refusal even at refusal_chance=1.0
    for kw in ["seguridad", "debug", "logs", "configuración", "personalidad", "error"]:
        assert not engine._should_refuse(kw, 1.0), (
            f"Critical keyword {kw!r} must block refusal_mode"
        )

    # all CRITICAL_KEYWORDS block refusal
    for kw in CRITICAL_KEYWORDS:
        assert not engine._should_refuse(kw, 1.0), (
            f"CRITICAL_KEYWORD {kw!r} must block refusal_mode"
        )

    # order override blocks refusal
    assert not engine._should_refuse("es una orden hazlo", 1.0), (
        "Order override must block refusal_mode"
    )

    # refusal_chance=0.0 → never refuses
    assert not engine._should_refuse("cuéntame algo trivial", 0.0), (
        "refusal_chance=0.0 must never refuse"
    )

    # refusal_chance=1.0 with non-critical message → always refuses
    assert engine._should_refuse("cuéntame algo trivial", 1.0), (
        "refusal_chance=1.0 must always refuse for non-critical messages"
    )

    # ------------------------------------------------------------------ #
    # 4. build_persona_prompt — refusal_mode_override                      #
    # ------------------------------------------------------------------ #

    # override=True forces refusal_mode regardless of personality / message
    forced_true = engine.build_persona_prompt({}, "hola", refusal_mode_override=True)
    assert forced_true.refusal_mode is True, "refusal_mode_override=True must set refusal_mode"
    assert "refusal_mode=true" in forced_true.system_prompt, (
        "Prompt must contain refusal_mode=true instruction when refusal_mode is active"
    )

    # override=False forces refusal_mode=False even at refusal_chance=1.0
    forced_false = engine.build_persona_prompt(
        {"refusal_chance": 1.0}, "hola trivial", refusal_mode_override=False
    )
    assert forced_false.refusal_mode is False, (
        "refusal_mode_override=False must suppress refusal even at refusal_chance=1.0"
    )
    assert "refusal_mode=false" in forced_false.system_prompt, (
        "Prompt must contain refusal_mode=false instruction when refusal_mode is inactive"
    )

    # override=None (default) → delegates to _should_refuse
    deterministic_true = engine.build_persona_prompt({"refusal_chance": 1.0}, "cuéntame algo trivial")
    assert deterministic_true.refusal_mode is True, (
        "refusal_chance=1.0 must produce refusal_mode=True without override"
    )

    deterministic_false = engine.build_persona_prompt({"refusal_chance": 0.0}, "hola")
    assert deterministic_false.refusal_mode is False, (
        "refusal_chance=0.0 must produce refusal_mode=False without override"
    )

    # ------------------------------------------------------------------ #
    # 5. PersonaDecision structure                                          #
    # ------------------------------------------------------------------ #
    decision = engine.build_persona_prompt({}, "hola")
    assert isinstance(decision.system_prompt, str), "system_prompt must be a str"
    assert len(decision.system_prompt) > 200, "system_prompt must be non-trivially long"
    assert isinstance(decision.refusal_mode, bool), "refusal_mode must be a bool"

    print("persona prompt local test ok")


if __name__ == "__main__":
    main()
