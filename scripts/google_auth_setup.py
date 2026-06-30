"""Ejecutar UNA SOLA VEZ para autorizar a Sity a acceder a Gmail, Calendar y Drive.

Muestra una URL para abrir en cualquier navegador (incluido el del PC aunque
accedas vía SSH). Tras autorizar, copia el código que muestra Google (o la URL
completa de redirección si el navegador redirige a una página que no carga) y
pégalo en la terminal.

Uso:
    cd ~/projects/sity
    python scripts/google_auth_setup.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from app.integrations.google_auth import run_initial_auth_flow, TOKEN_PATH


def main() -> None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Error: GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET no están en .env")
        sys.exit(1)

    print("Se mostrará una URL para autorizar a Sity.")
    print("Puedes abrirla en cualquier navegador, incluido el de tu PC.")
    print("Tras autorizar, copia el código (o la URL final) y pégalo aquí.")
    input("Pulsa Enter para continuar...")

    run_initial_auth_flow(client_id, client_secret)

    print(f"\nAutenticación completada. Token guardado en {TOKEN_PATH}")
    print("Sity ya puede usar Gmail, Calendar y Drive.")


if __name__ == "__main__":
    main()
