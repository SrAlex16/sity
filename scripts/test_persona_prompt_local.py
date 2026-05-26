#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from app.core.persona_engine import PersonaEngine  # noqa: E402

    personality: dict = {}
    prompt = PersonaEngine().build_persona_prompt(personality, "hola").system_prompt

    # --- Identidad ---
    required = [
        "Eres Sity",
    ]

    # --- Regla gramatical de género ---
    required += [
        "femenino gramatical",
        "español de España",
        # Ejemplos explícitos en el prompt (correcto / incorrecto)
        "Estoy lista",
        "Me siento vacía",
        "Estoy listo",    # aparece como ejemplo de forma incorrecta
        "Me siento vacío",
    ]

    # --- Regla de bienestar / seguridad ---
    required += [
        "No romantices autolesiones",
        "prioriza ayuda y seguridad",
    ]

    # --- Concepto de refusal_mode ---
    required += [
        "refusal_mode",
    ]

    missing = [f for f in required if f not in prompt]
    assert not missing, f"Missing persona prompt fragments: {missing}"

    # --- Invariante negativa: el prompt no debe contener pseudo-tool-calls ---
    # (ResponseGuard ya los bloquea en la respuesta del modelo, pero el system
    # prompt tampoco debería generarlos como plantilla de ejemplo)
    pseudo_tool_markers = ["<function_calls>", "<invoke ", "<attempt_tool_use>"]
    found_pseudo = [m for m in pseudo_tool_markers if m in prompt]
    assert not found_pseudo, f"Prompt contains pseudo-tool-call markers: {found_pseudo}"

    # TODO: el prompt no debe contener rutas absolutas personales
    # (actualmente contiene /home/alex/projects/sity — se resolverá en fase C)
    # assert "/home/alex/projects/sity" not in prompt

    # TODO: los servicios permitidos deben venir de una fuente única de config
    # (actualmente hardcodeados como "sity-backend y sity-frontend" — pendiente)
    # assert "sity-backend" not in prompt

    print("persona prompt local test ok")


if __name__ == "__main__":
    main()
