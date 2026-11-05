from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("elm")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


def _body(code: str, message: str, request: Request, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}, "request_id": getattr(request.state, "request_id", None)}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, request, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=_body("VALIDATION_ERROR", "Please correct the highlighted fields.", request, {"fields": errs}))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # never leak stack traces / SQL
        ref = uuid.uuid4().hex[:10]
        log.exception("Unhandled error ref=%s", ref)
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", f"Unexpected error (ref {ref}).", request))
