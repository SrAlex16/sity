"""Ejecutar UNA SOLA VEZ para autorizar a Sity a acceder a Spotify.

Antes de ejecutar, regístrate en https://developer.spotify.com/dashboard,
crea una app, y añade http://127.0.0.1:8888/callback como Redirect URI
en la configuración de la app. Copia el Client ID y Client Secret a .env.

Muestra una URL para abrir en cualquier navegador (incluido el del PC aunque
accedas vía SSH). Tras autorizar, Spotify redirige a http://127.0.0.1:8888/callback
— el navegador mostrará "página no disponible", lo cual es normal. Copia la
URL completa de la barra del navegador y pégala en la terminal.

Uso:
    cd ~/projects/sity
    python scripts/spotify_auth_setup.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from app.integrations.spotify_auth import REDIRECT_URI, TOKEN_PATH, run_initial_auth_flow


def main() -> None:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Error: SPOTIFY_CLIENT_ID o SPOTIFY_CLIENT_SECRET no están en .env")
        sys.exit(1)

    print("=" * 60)
    print("Configuración OAuth de Spotify para Sity")
    print("=" * 60)
    print()
    print("Requisito previo: en https://developer.spotify.com/dashboard")
    print(f"debes tener registrado este Redirect URI en tu app:")
    print(f"  {REDIRECT_URI}")
    print()
    input("Pulsa Enter para continuar y ver la URL de autorización...")

    run_initial_auth_flow(client_id, client_secret)

    print(f"\nAutenticación completada. Token guardado en {TOKEN_PATH}")
    print("Sity ya puede controlar Spotify.")


if __name__ == "__main__":
    main()
