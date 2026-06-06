import os
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRETS = {"change-me", "", "secret", "your-secret-key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://aigov:aigov@postgres:5432/aigov"
    )
    REDIS_URL: str = Field(default="redis://redis:6379/0")
    SECRET_KEY: str = Field(default="change-me")
    OPENAI_API_KEY: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")

    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30)

    DEBUG: bool = Field(default=False)
    FRONTEND_URL: str = Field(default="http://localhost:3000")

    SENTRY_DSN: str = Field(default="")
    ENVIRONMENT: str = Field(default="development")

    SPACY_MODEL: str = Field(default="en_core_web_lg")

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_not_be_default(cls, v: str) -> str:
        if v in WEAK_SECRETS:
            # Read DEBUG straight from env: at validator time the sibling
            # Settings field has not been assigned yet.
            debug = os.getenv("DEBUG", "false").lower() == "true"
            if not debug:
                raise ValueError(
                    "SECRET_KEY must be set to a strong random value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
        return v


def secret_key_is_weak(value: str) -> bool:
    return value in WEAK_SECRETS


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
