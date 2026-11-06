"""Create or upgrade the ELM schema, then seed it.

    python -m app.dbsetup            # alembic upgrade head + seed (demo or minimal, per ELM_SEED_DEMO_DATA)
    python -m app.dbsetup --no-seed  # schema only

On MySQL/MariaDB (the target, inside proflow_uat) the schema always comes from the Alembic migrations, so the
`elm_alembic_version` table stays correct. SQLite (tests and quick local trials) uses metadata.create_all.
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent


def upgrade_schema() -> None:
    from app.core.db import Base, engine
    import app.models  # noqa: F401

    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


def main(argv: list[str]) -> None:
    upgrade_schema()
    if "--no-seed" not in argv:
        from app.seed import run

        run()
    print("Database ready.")


if __name__ == "__main__":
    main(sys.argv[1:])
