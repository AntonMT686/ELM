# ADA-ELM — Engineering Lifecycle Management

Controlled engineering documents, configurable review/approval/signature workflows and a central release register for
**Aircraft → System → Subsystem → LRU → SRU/ECFM**, across ADA directorates. Built for an **offline intranet**.

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite, **Mantine 7** (core, dates, notifications, modals, spotlight, charts, dropzone), Tabler icons, TanStack Query, React Flow, PDF.js — all bundled locally |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Argon2id, PyJWT, cryptography |
| Data | PostgreSQL 16 (SQLite for local dev/tests), file storage volume (SHA-256 content addressed) |
| Editing | Self-hosted OnlyOffice Document Server (JWT) |
| Runtime | Docker Compose: `db`, `backend`, `worker`, `web` (nginx + SPA), optional `onlyoffice` |

## Quick start (Docker)

```bash
cp .env.example .env          # set passwords, OnlyOffice URLs + JWT secret
docker compose up -d --build  # http://localhost:8088
```
Demo users (password `Elm@12345`): `pe.kumar`, `eng.priya`, `chk.das`, `rev.joshi`, `td.menon`, `cm.sharma`, `pgd.rao`,
`dir.iyer`, `adm.babu`, `adm.head`, `proc.krishnan`, `qa.verma`, `admin`.

## Local development (no Docker)

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
ELM_ENVIRONMENT=dev uvicorn app.main:app --reload          # SQLite + demo seed, API docs at /api/docs
pytest -q                                                   # end-to-end API tests
cd ../frontend && npm install && npm run dev                # http://localhost:5173 (proxies /api)
```

## Migrating data from the old PMS
See [scripts/import_legacy/README.md](scripts/import_legacy/README.md): a read-only extract, then a dry-run-by-default load with reconciliation and rollback.

## Offline delivery
`deploy/scripts/build_offline_bundle.sh` (connected machine) → copy `dist/ada-elm-offline-*.tar.gz` →
`install_offline.sh` on the air-gapped server. See `Docs/HANDOFF.md` for status and next steps.
