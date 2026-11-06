# ADA-ELM — How to run (no Docker for the application)

ADA-ELM runs as **three normal processes** on the server plus the services it uses:

| Process / service | What it is | How it runs | Default port |
|---|---|---|---|
| **Backend** | FastAPI API (`python -m app.serve`) | Python virtual environment in `backend\.venv` | 8000 |
| **Worker** | SLA reminders, due dates, automation-job checks (`python -m app.worker`) | same virtual environment | — |
| **Frontend** | Web UI, serves `frontend\dist` and forwards `/api` to the backend (`npm run serve`) | Node.js | 8088 |
| MySQL / MariaDB | The existing **`proflow_uat`** database (XAMPP) | already running | 3309 (XAMPP) |
| OnlyOffice | Document editor | **Docker** (the only container) | 8080 |
| GitLab | Source control | already running in Docker | e.g. 8929 |
| draw.io (optional) | Diagram editor on the Design page | Docker or any static web server | 8081 |

Every setting is in **one file: `.env` in the repository folder** (template: `.env.example`). The backend, the worker
and the frontend server all read it. Restart them after changing it.

---

## 1. Prerequisites (developer PC or server)

| Software | Version | Notes |
|---|---|---|
| Python | 3.12 (3.11–3.13 work), 64-bit | Windows: tick *Add python.exe to PATH*; the `py` launcher is used if present |
| Node.js | 22 LTS (20+ works), 64-bit | includes npm |
| MySQL / MariaDB | the running `proflow_uat` (XAMPP 7.4.10 ships MariaDB 10.4; MySQL 8 also works) | InnoDB, `utf8mb4` |
| Docker | Docker Desktop (Windows) or Docker Engine (Linux) | **only** for OnlyOffice (and optionally draw.io) |
| GitLab | your running GitLab container | an access token with `api` scope |
| Browser | Edge / Chrome / Firefox, current | |

## 2. Database: ELM inside `proflow_uat`

ELM uses the **same database** as the legacy PMS, `proflow_uat`. Its own tables all start with **`elm_`** (for example
`elm_users`, `elm_requirements`, `elm_design_records`), so they never collide with the PMS tables (`user`,
`requirements`, `project_plans`, …). The legacy tables are not created, changed or dropped. The schema version is kept
in `elm_alembic_version`.

Two ways to create the ELM tables (choose one):

* **Recommended — automatic:** `setup.ps1` / `setup.sh` (below) runs `python -m app.dbsetup`, which applies every
  migration in `backend/migrations/versions` and seeds the reference data. Run it again after every update; it only
  applies what is new.
* **Manual, by a DBA, with SQL files** in `database/mysql/`:
  1. `00_create_elm_user.sql` — optional dedicated account `elm` (replace the password first).
  2. `01_elm_schema.sql` — `CREATE TABLE elm_*` statements and `ALTER TABLE` for keys.
  3. `02_elm_reference_data.sql` — roles, permissions, document types, workflows, design types, plan phases and the
     user `admin` / `ChangeMe@123` (change it at first sign-in).

  ```bat
  C:\xampp7410\mysql\bin\mysql.exe -u root -P 3309 proflow_uat < database\mysql\01_elm_schema.sql
  C:\xampp7410\mysql\bin\mysql.exe -u root -P 3309 proflow_uat < database\mysql\02_elm_reference_data.sql
  ```
  After a manual install, later releases still upgrade with `python -m app.dbsetup` (it reads `elm_alembic_version`).

In `.env`:
```ini
ELM_DATABASE_URL=mysql+pymysql://elm:<password>@127.0.0.1:3309/proflow_uat?charset=utf8mb4
```
Special characters in the password must be URL-encoded (`@` → `%40`, `#` → `%23`, `:` → `%3A`). XAMPP's default
`root` with an empty password is written `mysql+pymysql://root:@127.0.0.1:3309/proflow_uat?charset=utf8mb4`.

Demo data (`ELM_SEED_DEMO_DATA=true`) uses fictional people and generic product names (Product Alpha / Beta,
Product → System → Subsystem → Unit → Module). It is created only when the ELM tables are empty. For production set
`ELM_SEED_DEMO_DATA=false`: only `admin` is created, with the password in `ELM_ADMIN_PASSWORD`.

## 3. Windows: first-time setup

From PowerShell in the repository folder (for example `D:\Projects\products\ADA-ELM`):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1
```

1. The first run creates `.env` from `.env.example` with a random `ELM_SECRET_KEY`, opens it in Notepad and stops.
   Fill in at least `ELM_DATABASE_URL`, the OnlyOffice values (section 6) and, if wanted, GitLab (section 7).
2. Run the same command again. It creates `backend\.venv`, installs the Python packages, installs the Node packages,
   builds the frontend (`frontend\dist`) and creates/upgrades the `elm_*` tables.

Options: `-Offline` (only use the offline package; automatic when `offline\wheels` exists), `-RebuildFrontend`,
`-SkipDatabase`.

## 4. Windows: start and stop

| Action | Command |
|---|---|
| Start all three (three windows) | `deploy\windows\start-all.bat` |
| Start one | `deploy\windows\start-backend.bat`, `start-worker.bat`, `start-frontend.bat` |
| Stop all | `deploy\windows\stop-all.bat` (or close the windows) |
| Backup | `powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1 -MysqlBin C:\xampp7410\mysql\bin` |

Open **http://localhost:8088** (or `http://<server-name>:8088` from other PCs). Check the API at
http://localhost:8000/api/health.

Before starting: MySQL must be running (XAMPP Control Panel → MySQL → Start) and the OnlyOffice container must be up.
To start the three processes automatically at boot, create Windows Task Scheduler tasks ("At startup", "Run whether
user is logged on or not") for the three `start-*.bat` files, or wrap them as services with a tool ADA IT approves.

## 5. Linux: setup, start, stop

```bash
deploy/linux/setup.sh          # first run creates .env and stops; edit it, then run again
deploy/linux/start-all.sh      # background; logs in logs/, PIDs in logs/*.pid
deploy/linux/stop-all.sh
deploy/linux/backup.sh
```
Foreground alternatives: `deploy/linux/start-backend.sh`, `start-worker.sh`, `start-frontend.sh` (useful for systemd
units: one unit per script, `Restart=on-failure`, `WorkingDirectory=` the repository folder).

## 6. Development mode (hot reload)

Two terminals:

```bat
cd backend
.venv\Scripts\activate
set ELM_ENVIRONMENT=dev
python -m app.serve
```
```bat
cd frontend
npm run dev
```
Open http://localhost:5173. In `dev`, the backend upgrades the schema and seeds on start. Run the tests with
`cd backend && .venv\Scripts\python -m pip install -r requirements-dev.txt && .venv\Scripts\python -m pytest`
(SQLite by default; set `ELM_TEST_DATABASE_URL` to an **empty scratch** MySQL database to test on MySQL — never
`proflow_uat`).

## 7. OnlyOffice (Docker) and how the pieces find each other

If OnlyOffice already runs, only copy its URL and JWT secret into `.env`. Otherwise:
```bash
docker compose --env-file .env -f deploy/onlyoffice/docker-compose.yml up -d
```

| Setting | Who uses it | Value when everything is on one Windows server |
|---|---|---|
| `ELM_ONLYOFFICE_PUBLIC_URL` | users' browsers load the editor | `http://<server-name>:8080` |
| `ELM_ONLYOFFICE_INTERNAL_URL` | backend downloads saved files | `http://localhost:8080` |
| `ELM_BACKEND_INTERNAL_URL` | OnlyOffice container calls the backend | `http://host.docker.internal:8000` (Docker Desktop). Linux Docker: the host's LAN IP, e.g. `http://10.0.0.5:8000` |
| `ELM_ONLYOFFICE_JWT_SECRET` | both sides | the Document Server's JWT secret |

Get the secret of a running container:
`docker exec <container> /var/www/onlyoffice/documentserver/npm/json -f /etc/onlyoffice/documentserver/local.json services.CoAuthoring.secret.session.string`.
The container must allow calls to private addresses (`ALLOW_PRIVATE_IP_ADDRESS=true`). Port 8000 must be reachable
from the container (Windows Firewall: allow inbound TCP 8000 for Python).

## 8. GitLab integration

1. In GitLab create an access token with scope **`api`** (a service account or group token is best). Its access
   decides which projects ELM can use.
2. In `.env`:
   ```ini
   ELM_GITLAB_ENABLED=true
   ELM_GITLAB_URL=http://localhost:8929          # what the backend uses (the container's published HTTP port)
   ELM_GITLAB_PUBLIC_URL=http://<server>:8929    # what browsers use for links (if different)
   ELM_GITLAB_TOKEN=glpat-...
   ELM_GITLAB_WEBHOOK_SECRET=<long random text>
   ```
   Restart the backend.
3. In ELM, **Engineering → Source control**: pick the project and **Register repository** (`group/project`). Only
   registered repositories are ever called. The page shows whether GitLab is reachable.
4. In GitLab, for each registered project: *Settings → Webhooks* → URL `http://<ELM backend host>:8000/api/v1/scm/gitlab/webhook`,
   secret token = `ELM_GITLAB_WEBHOOK_SECRET`, triggers **Push events** and **Merge request events**. GitLab in Docker
   reaches the host as `host.docker.internal` (Docker Desktop) or the host IP; in *Admin → Settings → Network →
   Outbound requests* allow requests to the local network.
5. Work: create a task of kind **Development** (Tasks board → *Development*), open its **Code** tab, create the branch
   (`task/<KEY>-…`), push commits with the task key in the message, open the merge request from ELM. ELM links branches,
   commits and merge requests, moves the task to *Code review* when the MR opens and to *Merged* when an approved task's
   MR is merged. Code-review approval is given in ELM by the named reviewer, and a development task cannot be completed
   until its merge request is merged.

## 9. Optional: draw.io editor, test runners

* **draw.io**: `docker compose -f deploy/drawio/docker-compose.yml up -d`, then `ELM_DRAWIO_URL=http://<server>:8081` and
  rebuild nothing — restart backend and frontend (the frontend adds the origin to its CSP). Without it, diagrams are
  uploaded as `.drawio` / `.svg` / `.png` files.
* **Test automation**: `ELM_TEST_RUNNERS=playwright` and `ELM_TEST_RESULTS_TOKEN=<secret>`. A runner in its own
  controlled environment calls `POST /api/v1/test-automation/claim?tool=playwright` and
  `POST /api/v1/test-automation/results` with header `X-ELM-Runner-Token`. With no runner registered, queued jobs fail
  with a clear message (never a false pass).

## 10. Software deployments (architecture §14)

Engineering → **Deployments**. This is the release of software builds to environments; controlled documents are still
released in the Release register.

1. **Environments** tab (needs `deploy.configure`): add INT / UAT / PROD (or ADA's names) and set the gates: approvals,
   closed test run (of the same build), blocking defect severities, released document types, checklist, change window
   and blackout dates (in `ELM_TIMEZONE`), verified repository commit, secrets, adapter and health check. Someone else
   with `deploy.approve` approves the configuration; any later edit makes it a draft again.
2. **Request** a deployment (`deploy.request`): environment, version, repository/tag/commit, test run and the tasks it
   contains (release notes are drafted from them and their merge requests).
3. **Submit**: choose the approvers; the requester cannot approve. Environments without approval go straight to Approved.
4. **Deploy** (`deploy.execute`): every gate is checked and a failing one names what is missing. The attempt is queued
   and the worker runs it within `ELM_DEPLOY_POLL_SECONDS`:
   * **manual** — deploy by your usual procedure, then *Record result* (the health check still runs);
   * **GitLab pipeline** — ELM starts a pipeline on the tag/branch with `ELM_DEPLOYMENT`, `ELM_ENVIRONMENT`,
     `ELM_VERSION`, `ELM_COMMIT` variables and follows it;
   * **script** — a file in `ELM_DEPLOY_SCRIPTS_DIR` (`.ps1`, `.py`, `.bat`/`.sh`), called with
     `<environment> <version> <commit>`; secrets arrive only as `ELM_DEPLOY_SECRET_<NAME>` environment variables.
   A CI system can also report with `POST /api/v1/deployments/callback` signed with `ELM_DEPLOY_CALLBACK_SECRET`.
5. Logs are stored with passwords/tokens masked. A failure can be **retried** (new attempt, history kept). A deployed
   version can be **rolled back**: that creates a new deployment of the previous version, with the same approvals and
   gates; the original is marked *Rolled back* only when the rollback has succeeded.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| `setup.ps1` stops at the database step | MySQL running? URL, port (XAMPP 3309), password encoding, user rights on `proflow_uat` |
| UI loads but sign-in fails with a network error | backend window running? `ELM_API_URL` in `.env` points to it? |
| Editor shows "Download failed" / does not save | `ELM_BACKEND_INTERNAL_URL` reachable from the OnlyOffice container; firewall port 8000; JWT secret identical |
| Source control says "not reachable" | `ELM_GITLAB_URL` from the server itself (`curl http://localhost:8929/api/v4/version`), token scope `api` |
| Webhook deliveries fail in GitLab | URL reachable from the GitLab container; secret token equal; GitLab "allow local network requests" |
| Port already in use | change `ELM_API_PORT` / `ELM_WEB_PORT` in `.env` (and `ELM_API_URL`, `ELM_BACKEND_INTERNAL_URL`) |
