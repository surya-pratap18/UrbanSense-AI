from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # project root (where .env lives)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_name: str = "UrbanSense AI"
    environment: str = "development"
    city_slug: str = "bhubaneswar"

    database_url: str = ""
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173"
    cron_secret: str = ""
    admin_email: str = ""
    admin_password: str = ""

    openaq_api_key: str = ""
    tomtom_api_key: str = ""
    openaq_include_cuttack: bool = False
    tomtom_zoom: int = 12                 # zoom used for flow queries; segments are tied to it, so keep it constant
    tomtom_daily_budget: int = 2200       # self-imposed guard below TomTom's free 2,500 requests/day
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # protects TomTom's 2,500 requests/day free quota from "refresh" spam
    refresh_cooldown_seconds: int = 300

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if not url:
            return f"sqlite:///{ROOT / 'urbansense_dev.db'}"
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
