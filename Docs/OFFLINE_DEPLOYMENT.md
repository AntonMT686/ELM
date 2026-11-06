# ADA-ELM — Offline (air-gapped) deployment

The application does **not** run in Docker. On the offline server it runs as three processes (backend, worker,
frontend) from a Python virtual environment and Node.js, against the existing MySQL/MariaDB database **`proflow_uat`**.
Only **OnlyOffice** runs in Docker (and, optionally, draw.io). GitLab is the instance already running on the intranet.

Everything the server needs is prepared on a **connected PC** and carried over in one folder. Nothing is downloaded on
the offline server.

---

## 1. Prerequisites

### 1.1 Offline server — hardware

| Item | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores, 64-bit (x86_64), virtualization enabled in BIOS/UEFI (for Docker) | 8 cores |
| RAM | 8 GB (OnlyOffice alone needs 2–4 GB) | 16 GB |
| Disk | 30 GB free on SSD (software ~6 GB + data) | 200 GB+, sized to document and evidence volume |
| Network | fixed IP or DNS name on the intranet | |

### 1.2 Offline server — software (install these, in this order)

| # | Software | Version | Needed for | Installer in the package |
|---|---|---|---|---|
| 1 | Windows 10/11 Pro/Enterprise 64-bit 22H2+ (or Windows Server 2019/2022, or RHEL/Ubuntu x86_64) | — | OS | — |
| 2 | Microsoft Visual C++ Redistributable 2015–2022 x64 | latest 14.x | Python packages (cryptography, Pillow) | `offline\installers\vc_redist.x64.exe` |
| 3 | **Python** | **3.12.x, 64-bit** (must match `-PythonVersion` used for the package) | backend, worker | `offline\installers\python-3.12.x-amd64.exe` |
| 4 | **Node.js** | **22 LTS, 64-bit** (20+ works) | frontend server | `offline\installers\node-v22.x.x-x64.msi` |
| 5 | **MySQL / MariaDB** with `proflow_uat` | MariaDB 10.4+ (XAMPP 7.4.10) or MySQL 8.0+ | database | already installed (XAMPP) |
| 6 | **Docker Desktop** (+ WSL 2) on Windows, or Docker Engine 24+ on Linux | the version ADA IT approves | **OnlyOffice only** | `offline\installers\` if you add it |
| 7 | **OnlyOffice Document Server** | 8.2.2 (image) | editing Word/Excel/PowerPoint | `offline\images\onlyoffice-documentserver-8.2.2.tar` or the one already running |
| 8 | **GitLab** | the running intranet instance | source control | already running |
| 9 | Git client (developers' PCs) | 2.4x | commit and push to GitLab | `offline\installers\Git-2.x-64-bit.exe` if you add it |
| 10 | draw.io (optional) | jgraph/drawio 24.7.17 or the static webapp | embedded diagram editor | `offline\images\drawio-24.7.17.tar` (optional) |
| 11 | Browser on users' PCs | Edge / Chrome current | UI | — |

> Docker Desktop requires a paid subscription for organisations above 250 employees or USD 10 M revenue; on Windows
> Server use Docker Engine inside WSL 2 or a Linux host. Check with ADA IT. Docker is needed only for OnlyOffice.

### 1.3 Network ports on the server

| Port | Opened to | Purpose |
|---|---|---|
| 8088 | users | ELM web UI (`ELM_WEB_PORT`) |
| 8080 | users | OnlyOffice editor (browser loads it) |
| 8000 | the server itself, the OnlyOffice and GitLab containers | ELM backend API (`ELM_API_PORT`) |
| 3309 / 3306 | the server itself | MySQL/MariaDB (do not expose further) |
| 8929 (example) | users, server | GitLab |
| 8081 | users (optional) | draw.io |

### 1.4 Connected preparation PC

Same OS family and CPU as the server (Windows x64 for a Windows server). Installed: Python 3.12 (same minor version as
the server), Node.js 22, PowerShell 5.1+, internet access, and Docker only if you include the OnlyOffice/draw.io images.

## 2. Prepare the package (connected PC)

1. Download the installers listed in `deploy\offline\installers\PUT-INSTALLERS-HERE.txt` into that folder.
2. In PowerShell, from the repository folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\offline\prepare-offline-bundle.ps1 -PythonVersion 3.12
   ```
   Add `-IncludeOnlyOffice` if the server has no OnlyOffice yet, `-IncludeDrawio` for the diagram editor.
   (Linux server: `deploy/offline/prepare-offline-bundle.sh 0.2.0 3.12` on a connected Linux PC.)
3. Result: `dist\ADA-ELM-Offline-0.2.0\`:
   ```
   ADA-ELM-Offline-0.2.0\
     backend\  frontend\ (with dist\ built)  deploy\  database\  Docs\  scripts\
     .env.example   README-OFFLINE.md   SHA256SUMS.txt
     offline\wheels\      all Python packages for Windows x64 / Python 3.12
     offline\npm-cache\   all Node packages (installed with npm ci --offline)
     offline\images\      optional OnlyOffice / draw.io images
     offline\installers\  Python, Node.js, VC++ runtime, ...
   ```
4. Copy the whole folder to removable media and scan it according to ADA's media-transfer procedure.

## 3. What the package does not contain

No database contents, no `.env` secrets, no demo data files, no `node_modules` (rebuilt from the cache) and no virtual
environment (rebuilt from the wheels). The ELM tables are created on the server.

## 4. Install on the offline server

1. Copy the folder to the server, for example `D:\ADA-ELM`. Optional integrity check:
   ```powershell
   Get-Content SHA256SUMS.txt | ForEach-Object { $h, $f = $_ -split '  ', 2; if ((Get-FileHash $f).Hash -ne $h) { "BAD: $f" } }
   ```
2. Install the prerequisites from `offline\installers\` (section 1.2): VC++ runtime, Python 3.12 (tick
   *Add python.exe to PATH*), Node.js 22. Open a new PowerShell so PATH is refreshed. Check: `py -3.12 --version`,
   `node --version`.
3. OnlyOffice: if it is not running yet, `docker load -i offline\images\onlyoffice-documentserver-8.2.2.tar`, then set
   `ELM_ONLYOFFICE_JWT_SECRET` in `.env` (step 4) and run
   `docker compose --env-file .env -f deploy\onlyoffice\docker-compose.yml up -d`.
4. Run the setup (first run creates `.env` and opens it):
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1 -Offline
   ```
   In `.env` set at least:
   * `ELM_ENVIRONMENT=prod`, `ELM_SEED_DEMO_DATA=false`, `ELM_ADMIN_PASSWORD=<strong password>`
   * `ELM_DATABASE_URL=mysql+pymysql://elm:<pw>@127.0.0.1:3309/proflow_uat?charset=utf8mb4`
     (create the `elm` account with `database\mysql\00_create_elm_user.sql`, or use an existing account)
   * OnlyOffice: `ELM_ONLYOFFICE_PUBLIC_URL`, `ELM_ONLYOFFICE_INTERNAL_URL`, `ELM_ONLYOFFICE_JWT_SECRET`, `ELM_BACKEND_INTERNAL_URL`
   * GitLab: `ELM_GITLAB_ENABLED`, `ELM_GITLAB_URL`, `ELM_GITLAB_PUBLIC_URL`, `ELM_GITLAB_TOKEN`, `ELM_GITLAB_WEBHOOK_SECRET`
   * `VITE_DEMO_HINT=0`
   Then run the same command again. It installs the Python packages from `offline\wheels` (`pip --no-index`), the Node
   packages from `offline\npm-cache` (`npm ci --offline`), keeps the built `frontend\dist` and creates the `elm_*`
   tables in `proflow_uat` (`python -m app.dbsetup`).
   If the DBA prefers to run SQL by hand, use `database\mysql\01_elm_schema.sql` and `02_elm_reference_data.sql`
   first and add `-SkipDatabase`.
5. Start: `deploy\windows\start-all.bat`. Open `http://<server>:8088` and sign in as `admin`.
6. Windows Firewall: allow inbound TCP 8088 and 8080 from users; 8000 from the Docker network.
7. Autostart: Task Scheduler tasks "At startup" for `start-backend.bat`, `start-worker.bat`, `start-frontend.bat`
   (in that order, with a 30-second delay after MySQL/Docker), or the service wrapper ADA IT approves.

## 5. First configuration in ELM

1. Change the `admin` password (top-right menu).
2. Administration → Organization, Users & access, Roles: create directorates, people and scoped roles.
3. Administration → Projects & breakdown: create projects and their breakdown levels.
4. Engineering → Source control: register the GitLab repositories, then add the webhook in GitLab (see `Docs/RUNNING.md` §8).
5. Optional: import data from the legacy PMS (`scripts/import_legacy/README.md`).

## 6. Backup and restore

* Backup: `powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1 -MysqlBin C:\xampp7410\mysql\bin`
  writes `backups\elm-db-<time>.sql` (only `elm_*` tables), `elm-files-<time>.zip` (`data\storage`, `data\pki`) and
  checksums. Back up the PMS tables with the existing `proflow_uat` procedure. Keep `.env` in a secure place too.
* Restore: stop ELM, `mysql -u <user> -p proflow_uat < elm-db-<time>.sql`, unzip the files archive into the ELM folder,
  start ELM.

## 7. Upgrading to a new release

1. Prepare a new package on the connected PC (section 2).
2. On the server: stop ELM, take a backup, copy the new folder over the old one **keeping `.env`, `data\` and
   `backups\`**.
3. `powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1 -Offline -RebuildFrontend` (re-installs packages
   and applies new migrations; existing rows are kept), then start ELM.

## 8. Troubleshooting

See `Docs/RUNNING.md` §10. Typical offline-specific issues:

| Symptom | Cause / fix |
|---|---|
| `pip` says "No matching distribution" | package prepared for another Python minor version or OS; rebuild with the right `-PythonVersion` |
| `npm ci --offline` fails with ENOTCACHED | `package-lock.json` changed after the cache was filled; rebuild the package |
| `ImportError: DLL load failed` | install the VC++ 2015–2022 x64 runtime |
| OnlyOffice image not found | `docker load -i offline\images\onlyoffice-documentserver-8.2.2.tar` |
