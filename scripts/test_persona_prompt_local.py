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

    required_fragments = [
        "femenino gramatical",
        "español de España",
        "Estoy lista",
        "Me siento vacía",
        "Estoy listo",
        "Me siento vacío",
    ]

    missing = [f for f in required_fragments if f not in prompt]
    assert not missing, f"Missing persona prompt fragments: {missing}"

    print("persona prompt local test ok")


if __name__ == "__main__":
    main()
