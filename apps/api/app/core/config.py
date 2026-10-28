from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_title: str = "YottaFlex Routing & SLA API"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg2://yottaflex:yottaflex_dev@localhost:5432/yottaflex"

    ops_schema: str = "ops"
    gold_schema: str = "gold"


@lru_cache
def get_settings() -> Settings:
    return Settings()
