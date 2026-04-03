from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/avito_autoload"
    BASE_URL: str = "http://localhost:8000"
    MEDIA_DIR: str = "./media"
    FEEDS_DIR: str = "./feeds"
    SECRET_KEY: str = "change-me-in-production"
    CRM_DSN: str = ""
    BASIC_AUTH_USER: str = "admin"
    BASIC_AUTH_PASSWORD: str = "changeme"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

if settings.SECRET_KEY == "change-me-in-production":
    raise RuntimeError(
        "SECRET_KEY is not configured. Set a real key in .env: "
        "python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
