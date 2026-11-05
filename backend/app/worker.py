"""Background worker (DB-backed, no Redis required): SLA reminders / escalations, task and milestone due dates.
Run: python -m app.worker   (interval via ELM_WORKER_INTERVAL_SECONDS, default 900)."""
from __future__ import annotations

import logging
import os
import time

from app.core.db import SessionLocal
from app.services import planning_sweep, workflow_engine

log = logging.getLogger("elm.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def run_once() -> int:
    db = SessionLocal()
    try:
        n = workflow_engine.overdue_sweep(db) + planning_sweep.sweep(db)
        db.commit()
        return n
    except Exception:  # keep the worker alive; error is logged for operators
        db.rollback()
        log.exception("SLA sweep failed")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    interval = int(os.environ.get("ELM_WORKER_INTERVAL_SECONDS", "900"))
    log.info("ELM worker started (interval %ss)", interval)
    while True:
        log.info("SLA sweep: %s reminder(s) sent", run_once())
        time.sleep(interval)
