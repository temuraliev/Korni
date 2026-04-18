from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_group_id: int = Field(alias="ADMIN_GROUP_ID")
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list, alias="ADMIN_IDS")

    webhook_base_url: str = Field(alias="WEBHOOK_BASE_URL")
    webhook_secret: str = Field(alias="WEBHOOK_SECRET")
    port: int = Field(default=8080, alias="PORT")

    admin_login: str = Field(alias="ADMIN_LOGIN")
    admin_password: str = Field(alias="ADMIN_PASSWORD")
    session_secret: str = Field(alias="SESSION_SECRET")

    database_url: str = Field(alias="DATABASE_URL")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            return [int(part.strip()) for part in v.split(",") if part.strip()]
        raise TypeError(f"ADMIN_IDS must be str or list, got {type(v)}")

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v.removeprefix("postgres://")
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return "postgresql+asyncpg://" + v.removeprefix("postgresql://")
        return v

    @field_validator("webhook_base_url", mode="before")
    @classmethod
    def _normalize_webhook_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v:
            return v
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v

    @property
    def webhook_path(self) -> str:
        return f"/webhook/{self.webhook_secret}"

    @property
    def webhook_url(self) -> str:
        return self.webhook_base_url + self.webhook_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
