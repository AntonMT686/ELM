"""ADA-ELM FastAPI application (modular monolith)."""
from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1 import admin, auth, dashboard, documents, engineering, misc, onlyoffice, planning, releases, requirements, tasks, workflow
from app.core.config import get_settings
from app.core.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()

app = FastAPI(
    title="ADA ELM API",
    version="0.1.0",
    description="Engineering Lifecycle Management — documents, workflows, signatures and releases for Aircraft → System → LRU.",
    docs_url="/api/docs" if settings.environment != "prod" else None,
    openapi_url="/api/openapi.json" if settings.environment != "prod" else None,
    redoc_url=None,
)
install_error_handlers(app)

CSRF_EXEMPT = ("/api/v1/auth/login", "/api/v1/onlyoffice/callback/")


@app.middleware("http")
async def security_mw(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") and not request.url.path.startswith(CSRF_EXEMPT):
        cookie = request.cookies.get(settings.csrf_cookie_name, "")
        header = request.headers.get("X-CSRF-Token", "")
        if not cookie or not hmac.compare_digest(cookie, header):
            return JSONResponse(status_code=403, content={"error": {"code": "CSRF", "message": "Security token missing or invalid. Refresh the page.", "details": {}, "request_id": request.state.request_id}})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for r in (auth.router, admin.router, engineering.router, documents.router, workflow.router, releases.router, dashboard.router, misc.router, onlyoffice.router, tasks.router, planning.router, requirements.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.on_event("startup")
def _startup():  # dev convenience; production uses `alembic upgrade head` + `python -m app.seed`
    if settings.environment == "dev":
        from app.core.db import Base, engine
        import app.models  # noqa: F401

        Base.metadata.create_all(engine)
        from app.seed import run

        run()
