"""Application configuration. All values come from environment / .env (never hard-coded secrets)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# The backend, the worker and the frontend server all read ONE configuration file: <repository root>/.env.
# A backend/.env, if present, overrides it (handy on a developer PC). Real environment variables override both.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), env_prefix="ELM_", extra="ignore")

    app_name: str = "ADA ELM"
    environment: str = "dev"  # dev | uat | prod
    debug: bool = False

    # MySQL / MariaDB: the existing proflow_uat database, e.g. mysql+pymysql://elm:pw@localhost:3309/proflow_uat?charset=utf8mb4
    # (all ELM tables carry the elm_ prefix). SQLite is for automated tests only.
    database_url: str = "sqlite:///./elm_dev.db"
    storage_dir: Path = Path("./data/storage")
    pki_dir: Path = Path("./data/pki")

    secret_key: str = "change-me-dev-only-secret-key-please-rotate"
    access_token_minutes: int = 60 * 8
    cookie_secure: bool = False  # set True behind TLS in UAT/PROD
    cookie_name: str = "elm_session"
    csrf_cookie_name: str = "elm_csrf"

    api_host: str = "0.0.0.0"  # python -m app.serve binds here; OnlyOffice (in Docker) must be able to reach it
    api_port: int = 8000

    max_upload_mb: int = 200
    timezone: str = "Asia/Kolkata"

    # OnlyOffice Document Server (self-hosted on intranet)
    onlyoffice_enabled: bool = True
    onlyoffice_public_url: str = "http://localhost:8080"  # URL the *browser* uses to load api.js
    onlyoffice_internal_url: str = "http://localhost:8080"  # URL the backend may download saved files from
    onlyoffice_jwt_secret: str = ""
    onlyoffice_jwt_header: str = "Authorization"
    backend_internal_url: str = "http://host.docker.internal:8000"  # URL the OnlyOffice container uses to reach this backend

    # GitLab (self-hosted, on the intranet). Token is held server-side only and never sent to browsers.
    gitlab_enabled: bool = False
    gitlab_url: str = "http://localhost:8929"  # base URL the backend uses for the GitLab REST API
    gitlab_public_url: str = ""  # URL users' browsers use for GitLab links (defaults to gitlab_url)
    gitlab_token: str = ""  # personal / group / service-account access token with `api` scope
    gitlab_webhook_secret: str = ""  # X-Gitlab-Token value configured on the GitLab project webhook
    gitlab_timeout_seconds: int = 15

    # draw.io diagram editor served from the intranet (e.g. the jgraph/drawio container or its static webapp folder).
    # Empty = no embedded editor; diagrams are uploaded as .drawio / .svg / .png files instead.
    drawio_url: str = ""

    # Test automation (architecture §13.5): runners that may claim jobs, and the token they send (X-ELM-Runner-Token)
    test_runners: str = ""  # comma-separated tool names, e.g. "playwright"
    test_results_token: str = ""
    test_job_timeout_hours: int = 6

    # Software deployment (architecture §14). Scripts are taken only from this folder and only by the name in an approved
    # environment configuration. Secrets for deployments are ELM_DEPLOY_SECRET_<NAME> environment variables.
    deploy_scripts_dir: str = ""
    deploy_script_timeout_seconds: int = 1800
    deploy_timeout_hours: int = 6
    deploy_callback_secret: str = ""  # HMAC-SHA256 key for CI callbacks (X-ELM-Signature: sha256=<hex>)
    deploy_health_retry_seconds: float = 5.0

    # Digital signature provider: "dev_local_ca" (non-production) | adapter code registered later
    signature_provider: str = "dev_local_ca"

    seed_demo_data: bool = True
    demo_password: str = "Elm@12345"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Relative paths are taken from the repository root, so the backend and the worker find the same files whatever folder they start in.
    if not s.storage_dir.is_absolute():
        s.storage_dir = REPO_ROOT / s.storage_dir
    if not s.pki_dir.is_absolute():
        s.pki_dir = REPO_ROOT / s.pki_dir
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    s.pki_dir.mkdir(parents=True, exist_ok=True)
    return s
