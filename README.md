# ADA-ELM — Engineering Lifecycle Management

Controlled engineering documents, configurable review/approval/signature workflows, planning and tasks, requirements,
design artefacts, software development with GitLab, testing and defects, and a central release register for
**Product → System → Subsystem → Unit → Module/Component**, across ADA directorates. Built for an **offline intranet**.

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite, **Mantine 7**, Tabler icons, TanStack Query, React Flow, PDF.js — all bundled locally; served by `vite preview` (no nginx) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Argon2id, PyJWT, cryptography, reportlab |
| Data | **MySQL / MariaDB `proflow_uat`** (ELM tables prefixed `elm_`, legacy tables untouched); file store on disk (SHA-256) |
| Editing | Self-hosted OnlyOffice Document Server (JWT) — **the only Docker container** |
| Source control | Intranet GitLab (REST API + webhooks) |
| Runtime | Three processes: backend (`python -m app.serve`), worker (`python -m app.worker`), frontend (`npm run serve`) |

## Run it

Windows (PowerShell, in the repository folder):
```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1   # first run creates .env; edit it, run again
deploy\windows\start-all.bat                                         # http://localhost:8088
```
Linux: `deploy/linux/setup.sh` then `deploy/linux/start-all.sh`.

Full steps (database, OnlyOffice, GitLab, development mode, troubleshooting): **[Docs/RUNNING.md](Docs/RUNNING.md)**.
Air-gapped installation and the prerequisite list: **[Docs/OFFLINE_DEPLOYMENT.md](Docs/OFFLINE_DEPLOYMENT.md)**.
SQL scripts for the DBA: [database/mysql/](database/mysql/).

Demo users (password `Elm@12345`, only with `ELM_SEED_DEMO_DATA=true`): `pe.kumar`, `eng.priya`, `chk.das`, `rev.joshi`,
`td.menon`, `cm.sharma`, `pgd.rao`, `dir.iyer`, `adm.babu`, `adm.head`, `proc.krishnan`, `qa.verma`, `sw.rakesh`, `admin`.
All demo names are fictional and generic.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest -q        # SQLite
ELM_TEST_DATABASE_URL="mysql+pymysql://user:pw@127.0.0.1:3306/elm_test?charset=utf8mb4" pytest -q   # empty scratch MySQL DB
```

## Migrating data from the old PMS
See [scripts/import_legacy/README.md](scripts/import_legacy/README.md): a read-only extract, then a dry-run-by-default load with reconciliation and rollback.

Status, decisions and next steps: [Docs/HANDOFF.md](Docs/HANDOFF.md).
