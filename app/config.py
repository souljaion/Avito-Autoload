from cryptography.fernet import Fernet

from pydantic import model_validator
from pydantic_settings import BaseSettings

_WEAK_PASSWORDS = {"changeme", "password", "admin", ""}


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/avito_autoload"
    BASE_URL: str = "http://localhost:8000"
    MEDIA_DIR: str = "./media"
    FEEDS_DIR: str = "./feeds"
    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""
    CRM_DSN: str = ""
    BASIC_AUTH_USER: str = "admin"
    BASIC_AUTH_PASSWORD: str = "changeme"
    SENTRY_DSN: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode='after')
    def validate_credentials(self) -> 'Settings':
        if self.BASIC_AUTH_PASSWORD in _WEAK_PASSWORDS:
            raise ValueError(
                "BASIC_AUTH_PASSWORD is set to a weak default value. "
                "Set a strong password in .env before starting."
            )
        if self.ENCRYPTION_KEY:
            try:
                Fernet(self.ENCRYPTION_KEY.encode())
            except Exception:
                raise ValueError(
                    "ENCRYPTION_KEY is not a valid Fernet key. "
                    "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
        if self.CRM_DSN:
            valid_prefixes = ("postgresql://", "postgresql+asyncpg://")
            if not self.CRM_DSN.startswith(valid_prefixes):
                raise ValueError(
                    f"CRM_DSN must start with 'postgresql://' or "
                    f"'postgresql+asyncpg://', got: {self.CRM_DSN[:30]!r}"
                )
        return self


settings = Settings()

if settings.SECRET_KEY == "change-me-in-production":
    raise RuntimeError(
        "SECRET_KEY is not configured. Set a real key in .env: "
        "python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
