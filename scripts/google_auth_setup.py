"""Ejecutar UNA SOLA VEZ para autorizar a Sity a acceder a Gmail, Calendar y Drive.

Abre una URL en el navegador — debe ejecutarse desde un entorno con navegador
disponible (la Pi con escritorio, o reenviando el puerto si se ejecuta por SSH).

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

    print("Se abrirá una ventana del navegador para autorizar a Sity.")
    print("Inicia sesión con la cuenta de Google que quieras conectar.")
    input("Pulsa Enter para continuar...")

    run_initial_auth_flow(client_id, client_secret)

    print(f"\nAutenticación completada. Token guardado en {TOKEN_PATH}")
    print("Sity ya puede usar Gmail, Calendar y Drive.")


if __name__ == "__main__":
    main()
