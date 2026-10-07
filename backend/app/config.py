from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32
DEV_JWT_SECRET = "dev-only-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    # A aplicação conecta com um role sem BYPASSRLS; migrations usam o dono do schema.
    database_url: str = "postgresql+asyncpg://hora_app:hora_app@localhost:5432/hora_cravada"
    migration_database_url: str = "postgresql+asyncpg://hora:hora@localhost:5432/hora_cravada"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    @model_validator(mode="after")
    def reject_weak_secret_in_production(self) -> Self:
        if self.environment != "production":
            return self
        if self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET precisa ser definido em produção.")
        # HS256 pede uma chave com pelo menos 256 bits (RFC 7518, seção 3.2).
        if len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET precisa ter pelo menos {MIN_JWT_SECRET_BYTES} bytes.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
