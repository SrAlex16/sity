"""Fernet symmetric encryption for sensitive data at rest (e.g. OAuth tokens).

Key is read from SITY_ENCRYPTION_KEY (base64url-encoded, 32 bytes).
Generate once with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.environ.get("SITY_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("SITY_ENCRYPTION_KEY no está configurada")
    return Fernet(key.encode())


def encrypt_str(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_str(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("No se pudo descifrar: clave incorrecta o datos corruptos") from exc
