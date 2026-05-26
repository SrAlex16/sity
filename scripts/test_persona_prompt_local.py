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

    # La plantilla no debe contener rutas absolutas personales hardcodeadas.
    # La ruta del proyecto se inyecta desde runtime_config.project_root.
    from app.core.persona_engine import _TEMPLATE_PATH  # noqa: E402
    template_source = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "/home/alex/projects/sity" not in template_source, (
        "persona_system.md contains hardcoded personal path — use {project_root} placeholder"
    )

    # La plantilla no debe contener nombres de servicio hardcodeados.
    # Los servicios se inyectan desde get_allowed_systemd_services() → system_access.yaml.
    assert "sity-backend" not in template_source, (
        "persona_system.md contains hardcoded service name — use {allowed_systemd_services} placeholder"
    )

    print("persona prompt local test ok")


if __name__ == "__main__":
    main()
