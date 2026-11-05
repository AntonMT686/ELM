"""Application configuration. All values come from environment / .env (never hard-coded secrets)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ELM_", extra="ignore")

    app_name: str = "ADA ELM"
    environment: str = "dev"  # dev | uat | prod
    debug: bool = False

    database_url: str = "sqlite:///./elm_dev.db"
    storage_dir: Path = Path("./data/storage")
    pki_dir: Path = Path("./data/pki")

    secret_key: str = "change-me-dev-only-secret-key-please-rotate"
    access_token_minutes: int = 60 * 8
    cookie_secure: bool = False  # set True behind TLS in UAT/PROD
    cookie_name: str = "elm_session"
    csrf_cookie_name: str = "elm_csrf"

    max_upload_mb: int = 200
    timezone: str = "Asia/Kolkata"

    # OnlyOffice Document Server (self-hosted on intranet)
    onlyoffice_enabled: bool = True
    onlyoffice_public_url: str = "http://localhost:8080"  # URL the *browser* uses to load api.js
    onlyoffice_internal_url: str = "http://localhost:8080"  # URL the backend may download saved files from
    onlyoffice_jwt_secret: str = ""
    onlyoffice_jwt_header: str = "Authorization"
    backend_internal_url: str = "http://host.docker.internal:8000"  # URL OnlyOffice uses to reach backend

    # Digital signature provider: "dev_local_ca" (non-production) | adapter code registered later
    signature_provider: str = "dev_local_ca"

    seed_demo_data: bool = True
    demo_password: str = "Elm@12345"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    s.pki_dir.mkdir(parents=True, exist_ok=True)
    return s
