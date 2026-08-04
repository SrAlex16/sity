"""Tests for backend/app/auth/encryption.py — Fernet symmetric encryption."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.auth.encryption import decrypt_str, encrypt_str


@pytest.fixture()
def valid_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SITY_ENCRYPTION_KEY", key)
    return key


@pytest.fixture()
def alt_key() -> str:
    return Fernet.generate_key().decode()


class TestEncryptDecryptRoundtrip:
    def test_roundtrip_simple(self, valid_key: str) -> None:
        original = "hello world"
        assert decrypt_str(encrypt_str(original)) == original

    def test_roundtrip_json(self, valid_key: str) -> None:
        payload = '{"access_token": "tok_abc", "refresh_token": "ref_xyz", "expires_at": 9999}'
        assert decrypt_str(encrypt_str(payload)) == payload

    def test_roundtrip_unicode(self, valid_key: str) -> None:
        payload = "clave secreta con ñ y émojis 🔑"
        assert decrypt_str(encrypt_str(payload)) == payload

    def test_ciphertext_differs_from_plaintext(self, valid_key: str) -> None:
        plaintext = "secret"
        assert encrypt_str(plaintext) != plaintext

    def test_same_plaintext_produces_different_ciphertext(self, valid_key: str) -> None:
        # Fernet includes a random IV — two encryptions of the same string must differ.
        plaintext = "same input"
        assert encrypt_str(plaintext) != encrypt_str(plaintext)


class TestWrongKey:
    def test_wrong_key_raises_value_error(
        self, valid_key: str, alt_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ciphertext = encrypt_str("secret data")
        monkeypatch.setenv("SITY_ENCRYPTION_KEY", alt_key)
        with pytest.raises(ValueError, match="clave incorrecta"):
            decrypt_str(ciphertext)

    def test_corrupted_ciphertext_raises_value_error(self, valid_key: str) -> None:
        with pytest.raises(ValueError, match="clave incorrecta"):
            decrypt_str("not-valid-fernet-token")


class TestMissingKey:
    def test_encrypt_without_key_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SITY_ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SITY_ENCRYPTION_KEY"):
            encrypt_str("test")

    def test_decrypt_without_key_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SITY_ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SITY_ENCRYPTION_KEY"):
            decrypt_str("anything")
