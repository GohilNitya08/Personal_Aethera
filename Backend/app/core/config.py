"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and ``.env``."""

    app_name: str = "AETHERA API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "aethera_user"
    mysql_password: str = ""
    mysql_database: str = "aethera"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """Build a MySQL URL while safely escaping credential values."""
        return URL.create(
            drivername="mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
        ).render_as_string(hide_password=False)

    @property
    def cors_origins_list(self) -> list[str]:
        """Convert a comma-separated CORS setting into a clean origin list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""
    return Settings()


settings = get_settings()
