"""Start the ELM backend as a normal process (no Docker): prepare the database, then run uvicorn.

    python -m app.serve              # host/port from .env (ELM_API_HOST / ELM_API_PORT)
    python -m app.serve --no-migrate # skip `dbsetup` (when another process already did it)
"""
from __future__ import annotations

import sys

import uvicorn

from app.core.config import get_settings


def main(argv: list[str]) -> None:
    s = get_settings()
    if s.environment != "dev" and "--no-migrate" not in argv:
        # dev does this on startup; uat/prod do it here so the schema is current before the first request.
        from app.dbsetup import main as dbsetup

        dbsetup([])
    uvicorn.run("app.main:app", host=s.api_host, port=s.api_port, proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="info")


if __name__ == "__main__":
    main(sys.argv[1:])
