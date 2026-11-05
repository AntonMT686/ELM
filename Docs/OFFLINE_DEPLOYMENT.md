# ADA-ELM — Offline (Air-gapped) Deployment on Windows

Everything runs in Docker containers: **web** (nginx + UI), **backend** (FastAPI), **worker**, **db** (PostgreSQL),
**onlyoffice** (document editor). The offline server needs **no Python, Node.js, PostgreSQL or internet**: only Docker Desktop.

---

## 1. Server requirements

| Item | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11 Pro or Enterprise, 64-bit, version 22H2 or later | Windows 11 Enterprise 23H2+ |
| CPU | 4 cores, **virtualization enabled in BIOS/UEFI** (Intel VT-x / AMD-V) | 8 cores |
| RAM | 8 GB | 16 GB (OnlyOffice alone uses 2–4 GB) |
| Disk | 40 GB free (images ~5 GB + data) on an SSD | 200 GB+ according to document volume |
| Network | Fixed IP or DNS name on the intranet; inbound TCP **8088** (ELM) and **8080** (editor) open | |

> **Windows Server note:** Docker Desktop is officially supported on Windows 10/11 only. On Windows Server 2019/2022,
> Linux containers need WSL2 + Docker Engine inside a Linux distro, or a Linux VM/host. Confirm with ADA IT before
> choosing Windows Server. A Linux host (RHEL/Ubuntu + Docker Engine) is also a supported alternative.
>
> **Licensing:** Docker Desktop needs a paid Docker subscription for organizations with more than 250 employees or more
> than USD 10 M revenue. Check with ADA IT/procurement.

## 2. Software to install on the offline server (only these)

| # | Tool | Version | Where to get it (download on the connected PC) |
|---|---|---|---|
| 1 | Windows features **Virtual Machine Platform** + **Windows Subsystem for Linux** | built into Windows | enabled with DISM (step 4.1), no download |
| 2 | **WSL** package | 2.3.x or later (`wsl.2.x.x.0.x64.msi`) | https://github.com/microsoft/WSL/releases |
| 3 | **Docker Desktop for Windows** | **the same version as on your build PC** (4.37 or later; check with `docker version`). Includes Docker Engine 27+ and Compose v2 | https://docs.docker.com/desktop/release-notes/ → "Docker Desktop Installer.exe" |
| 4 | A browser | Microsoft Edge / Chrome (already on Windows) | — |

Container images inside the package (fixed versions, nothing to download):

| Image | Version |
|---|---|
| `ada-elm/backend` | 0.1.0 (Python 3.12, FastAPI 0.115.6) |
| `ada-elm/web` | 0.1.0 (nginx 1.27, React 18 + Mantine 7.15) |
| `postgres` | 16.6-alpine |
| `onlyoffice/documentserver` | 8.2.2 |

## 3. On the CONNECTED PC: build the package

1. Put `Docker Desktop Installer.exe` and `wsl.*.x64.msi` into `deploy\offline\installers\`.
2. In PowerShell, from `D:\Projects\products\ADA-ELM`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\offline\prepare-offline-bundle.ps1
   ```
   This builds the ELM images, pulls PostgreSQL and OnlyOffice, saves all four images, copies the scripts and writes `SHA256SUMS.txt`.
   If the offline server **already runs OnlyOffice**, add `-SkipOnlyOffice` to leave out the OnlyOffice image (package about 2.5 GB smaller).
   If it already has Docker Desktop and WSL, you don't need the installers.
3. Result: **`dist\ADA-ELM-Offline-0.1.0\`** (about 4–5 GB):
   ```
   ADA-ELM-Offline-0.1.0\
     START-ADA-ELM.bat     STOP-ADA-ELM.bat   STATUS-ADA-ELM.bat   BACKUP-ADA-ELM.bat
     elm.ps1               docker-compose.yml README-OFFLINE.md    SHA256SUMS.txt
     images\  (4 .tar files + IMAGES.txt)
     installers\  (Docker Desktop + WSL)
   ```
4. Copy **the whole folder** to approved transfer media, then to the server, for example to `D:\ADA-ELM\`. Use a path without spaces if possible.

## 4. On the OFFLINE server: one-time prerequisites

> **Already have Docker Desktop + WSL 2 (and maybe OnlyOffice) on the server? Skip 4.1–4.3.** Run only the check below.
> If every line passes, go straight to step 5.
> ```powershell
> wsl --status                          # Default Version: 2
> docker version                        # Client AND Server shown (Engine 24+, ideally 27+)
> docker info --format "{{.OSType}}"    # linux
> docker compose version                # v2.20 or newer
> net localgroup docker-users           # your account is listed
> ```
> Also confirm that Docker Desktop → Settings → General → "Start Docker Desktop when you sign in" is ticked.

Run in **PowerShell as Administrator**:

### 4.1 Enable Windows features, then reboot
```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Restart-Computer
```

### 4.2 Install WSL and set version 2
```powershell
cd D:\ADA-ELM\ADA-ELM-Offline-0.1.0\installers
msiexec /i (Get-ChildItem wsl*.msi).FullName /quiet /norestart
wsl --set-default-version 2
wsl --status
```

### 4.3 Install Docker Desktop (offline, silent)
```powershell
Start-Process ".\Docker Desktop Installer.exe" -Wait -ArgumentList "install","--quiet","--accept-license","--backend=wsl-2","--always-run-service"
net localgroup docker-users "$env:USERNAME" /add
```
Sign out and back in (or reboot). Then start **Docker Desktop** once:
- Accept the agreement and skip sign-in (no internet is needed).
- Settings → General: tick **"Start Docker Desktop when you sign in"**.
- Make sure it shows **Engine running** and is in **Linux containers** mode.

Check:
```powershell
docker version          # Client and Server both shown
docker compose version  # v2.x
```

Optional, to cap the memory WSL uses: create `%UserProfile%\.wslconfig` containing
`[wsl2]` and `memory=12GB` on separate lines, then run `wsl --shutdown`.

## 5. Start ADA-ELM (one click)

Double-click **`START-ADA-ELM.bat`** and allow the Administrator prompt.

On the **first run** it automatically:
1. Checks Docker (and starts Docker Desktop if needed).
2. Verifies every file against `SHA256SUMS.txt`.
3. Loads the 4 images (about 3–5 minutes).
4. Asks a few questions: **server name/IP** users will type (default: computer name), **web port** (8088) and **load demo data?** (N for real use).
   - **If an OnlyOffice container is already running**, it is detected automatically and offered for reuse (answer **Y**). Its port and JWT secret are read from the container, and the bundled OnlyOffice is not loaded or started. It also checks that the container allows private IPs. If not, it prints the fix: re-create the container with `-e ALLOW_PRIVATE_IP_ADDRESS=true`, or editing and saving fails with "Download failed".
   - Otherwise it starts the bundled OnlyOffice 8.2.2 on port 8080 (8081 if 8080 is already taken).
5. Generates all secrets into `.env`: database password, session key, OnlyOffice JWT and admin password. **No manual JWT setup is needed**, because ELM and OnlyOffice are configured with the same generated secret.
6. Creates the Windows firewall rule for both ports.
7. Starts all containers, waits for ELM and OnlyOffice to become healthy (OnlyOffice takes 2–3 minutes the first time) and opens the browser.

The sign-in details are written to **`ADMIN-CREDENTIALS.txt`**: user `admin` with a generated password, or the demo users if you chose demo data. Change the password, then delete that file.

Users on other PCs open: **`http://<server-name>:8088`**

Later runs of `START-ADA-ELM.bat` keep the existing `.env` and data, and just start the containers.
After a reboot, containers start automatically once Docker Desktop is running. Docker Desktop starts when a user signs in, so keep the server's service account signed in, or configure auto-logon per ADA policy.

## 6. Daily operation

| Task | Do this |
|---|---|
| Stop (data kept) | `STOP-ADA-ELM.bat` |
| Status + recent logs | `STATUS-ADA-ELM.bat` |
| Backup (DB + documents + signing keys + .env) | `BACKUP-ADA-ELM.bat` → `backups\<timestamp>\`. Copy it to separate media. |
| Full logs | `docker compose logs -f backend` (run in the package folder) |

**Restore** (PowerShell in the package folder, with ELM stopped except the db container):
```powershell
docker compose up -d db
docker compose cp backups\<ts>\elm-db.dump db:/tmp/elm.dump
docker compose exec db pg_restore -U elm -d elm --clean --if-exists /tmp/elm.dump
docker run --rm -v ada-elm_elm-files:/data -v ${PWD}\backups\<ts>:/backup postgres:16.6-alpine sh -c "cd /data && tar xzf /backup/elm-files.tgz"
START-ADA-ELM.bat
```

## 7. Upgrading to a new version
On the connected PC, rebuild the package with the new version (`-Version 0.2.0`). On the server: run `BACKUP-ADA-ELM.bat`, then `STOP-ADA-ELM.bat`. Copy the new folder, copy the old `.env` into it, and run `START-ADA-ELM.bat`. Database migrations run automatically.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| "Docker is not installed" / "engine did not start" | Re-check step 4. Virtualization must be enabled in BIOS. Check `wsl --status`. |
| "Windows-containers mode" | Docker tray icon → *Switch to Linux containers* |
| "Port 8088 is already used" | Edit `ELM_HTTP_PORT` in `.env` (or `ELM_ONLYOFFICE_PORT`), then run START again |
| Editor shows "Download failed" | Usually the server name in `.env` (`ELM_SERVER_HOST`) can't be resolved from client PCs. Use the IP address, then run STOP and START. |
| Other PCs can't open the site | Firewall: run START as Administrator once, or allow inbound TCP 8088 and 8080 |
| Anything else | `STATUS-ADA-ELM.bat`, plus `elm-install.log` in the package folder |
