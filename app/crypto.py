"""Fernet encrypt/decrypt helpers for sensitive fields."""

from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Cannot encrypt/decrypt secrets."
        )
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    """Encrypt a plaintext string, return base64-encoded ciphertext."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a base64-encoded ciphertext, return plaintext string."""
    return _get_fernet().decrypt(value.encode()).decode()
