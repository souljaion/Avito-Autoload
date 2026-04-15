"""Tests for app.crypto encrypt/decrypt."""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken


class TestCrypto:
    def test_roundtrip(self):
        """Encrypt then decrypt returns original value."""
        key = Fernet.generate_key().decode()
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key
            from app.crypto import encrypt, decrypt
            original = "my-super-secret-client-secret"
            ciphertext = encrypt(original)
            assert ciphertext != original
            assert decrypt(ciphertext) == original

    def test_different_plaintexts_produce_different_ciphertexts(self):
        """Different inputs should produce different outputs."""
        key = Fernet.generate_key().decode()
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key
            from app.crypto import encrypt
            c1 = encrypt("secret-one")
            c2 = encrypt("secret-two")
            assert c1 != c2

    def test_wrong_key_raises(self):
        """Decrypting with wrong key should raise."""
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key1
            from app.crypto import encrypt, decrypt
            ciphertext = encrypt("test-secret")

        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key2
            from app.crypto import decrypt as decrypt2
            with pytest.raises(InvalidToken):
                decrypt2(ciphertext)

    def test_no_key_raises_runtime_error(self):
        """Missing ENCRYPTION_KEY should raise RuntimeError."""
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = ""
            from app.crypto import encrypt
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is not set"):
                encrypt("test")

    def test_encrypt_produces_base64_string(self):
        """Ciphertext should be a base64-decodable string."""
        import base64
        key = Fernet.generate_key().decode()
        with patch("app.crypto.settings") as mock_settings:
            mock_settings.ENCRYPTION_KEY = key
            from app.crypto import encrypt
            ciphertext = encrypt("test-value")
            # Should be valid base64
            base64.urlsafe_b64decode(ciphertext)
