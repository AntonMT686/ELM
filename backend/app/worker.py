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
        from app.api.v1.testing import sweep_automation

        n = workflow_engine.overdue_sweep(db) + planning_sweep.sweep(db) + sweep_automation(db)
        db.commit()
        return n
    except Exception:  # keep the worker alive; error is logged for operators
        db.rollback()
        log.exception("SLA sweep failed")
        return 0
    finally:
        db.close()


def run_deployments_once() -> int:
    """Deployment attempts (architecture §14.3) need a short cycle, so they run on their own interval."""
    from app.services.deployment import run_pending

    db = SessionLocal()
    try:
        n = run_pending(db)
        db.commit()
        return n
    except Exception:
        db.rollback()
        log.exception("Deployment step failed")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    interval = int(os.environ.get("ELM_WORKER_INTERVAL_SECONDS", "900"))
    deploy_every = int(os.environ.get("ELM_DEPLOY_POLL_SECONDS", "20"))
    log.info("ELM worker started (sweeps every %ss, deployments every %ss)", interval, deploy_every)
    last_sweep = 0.0
    while True:
        if time.monotonic() - last_sweep >= interval:
            log.info("SLA sweep: %s reminder(s) sent", run_once())
            last_sweep = time.monotonic()
        done = run_deployments_once()
        if done:
            log.info("Deployments: %s attempt step(s) processed", done)
        time.sleep(deploy_every)
