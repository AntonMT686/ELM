<#
  ADA-ELM offline control script (Windows). Called by START/STOP/STATUS/BACKUP .bat files.
  Usage: powershell -ExecutionPolicy Bypass -File elm.ps1 <start|stop|status|backup|logs>
#>
param([ValidateSet("start", "stop", "status", "backup", "logs")][string]$Action = "start")
# "Continue": native tools (docker) write progress to stderr, which "Stop" would treat as fatal in Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$EnvFile = Join-Path $PSScriptRoot ".env"
$Log = Join-Path $PSScriptRoot "elm-install.log"

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan; Add-Content $Log "$(Get-Date -f s) $t" }
function Ok($t)   { Write-Host "    OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    !!  $t" -ForegroundColor Yellow; Add-Content $Log "WARN $t" }
function Fail($t) { Write-Host "`n    XX  $t`n" -ForegroundColor Red; Add-Content $Log "FAIL $t"; exit 1 }
function NewSecret([int]$n = 32) {
  $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
  $bytes = New-Object byte[] $n
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}
function ReadEnv {
  $h = @{}
  if (Test-Path $EnvFile) { Get-Content $EnvFile | Where-Object { $_ -match "^\s*[A-Z_]+=" } | ForEach-Object { $k, $v = $_ -split "=", 2; $h[$k.Trim()] = $v.Trim() } }
  return $h
}
function Compose { & docker compose --env-file $EnvFile -f (Join-Path $PSScriptRoot "docker-compose.yml") @args }

# ---------------------------------------------------------------- Docker engine
function EnsureDocker {
  Step "Checking Docker"
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed. Install Docker Desktop first (see README-OFFLINE.md, section 2)."
  }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) {
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Warn "Docker engine not running - starting Docker Desktop..."; Start-Process $dd }
    $t = 0
    do { Start-Sleep 5; $t += 5; docker info *> $null } while ($LASTEXITCODE -ne 0 -and $t -lt 240)
    if ($LASTEXITCODE -ne 0) { Fail "Docker engine did not start within 4 minutes. Open Docker Desktop and check for errors." }
  }
  $os = (docker info --format "{{.OSType}}").Trim()
  if ($os -ne "linux") { Fail "Docker is in Windows-containers mode. Right-click the Docker tray icon -> 'Switch to Linux containers', then retry." }
  docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 not available. Update Docker Desktop." }
  Ok ("Docker " + (docker version --format "{{.Server.Version}}") + " (linux engine), " + (docker compose version --short))
}

# ---------------------------------------------------------------- package integrity + images
function VerifyPackage {
  $marker = Join-Path $PSScriptRoot ".verified"
  if (Test-Path $marker) { return }
  Step "Verifying package checksums (first run only)"
  $sums = Join-Path $PSScriptRoot "SHA256SUMS.txt"
  if (-not (Test-Path $sums)) { Warn "SHA256SUMS.txt missing - skipping verification"; return }
  $bad = 0
  foreach ($line in Get-Content $sums) {
    if ($line -notmatch "^([A-F0-9]{64})\s+(.+)$") { continue }
    $f = Join-Path $PSScriptRoot $matches[2]
    if ($matches[2] -match "README-OFFLINE.md$") { continue }
    if (-not (Test-Path $f)) { Warn "missing: $($matches[2])"; $bad++; continue }
    if ((Get-FileHash $f -Algorithm SHA256).Hash -ne $matches[1]) { Warn "checksum mismatch: $($matches[2])"; $bad++ }
  }
  if ($bad) { Fail "$bad file(s) missing or corrupted. Copy the package again." }
  Set-Content $marker (Get-Date -f s); Ok "All files intact"
}

function LoadImages {
  Step "Loading container images"
  $list = Join-Path $PSScriptRoot "images\IMAGES.txt"
  if (-not (Test-Path $list)) { Fail "images\IMAGES.txt not found - is this the complete offline package?" }
  $envh = ReadEnv
  foreach ($line in Get-Content $list) {
    $name, $file = $line -split "`t"
    if ($name -like "onlyoffice/*" -and $envh["ELM_ONLYOFFICE_MODE"] -eq "existing") { Ok "skipping $name (using the OnlyOffice already running on this server)"; continue }
    if (-not (Test-Path (Join-Path $PSScriptRoot "images\$file"))) { if ($name -like "onlyoffice/*") { Warn "$file not in package - OnlyOffice must already be running"; continue } else { Fail "images\$file missing" } }
    docker image inspect $name *> $null
    if ($LASTEXITCODE -eq 0) { Ok "$name already loaded"; continue }
    Write-Host "    ... loading $name (may take a few minutes)"
    docker load -i (Join-Path $PSScriptRoot "images\$file")
    if ($LASTEXITCODE -ne 0) { Fail "docker load failed for $file" }
    Ok "$name loaded"
  }
}

# ---------------------------------------------------------------- first-run configuration
function FindExistingOnlyOffice {
  # Returns @{Name; Port; Secret; PrivateIpOk} for a running OnlyOffice container, or $null
  $rows = docker ps --format "{{.Names}}|{{.Image}}|{{.Ports}}" 2>$null | Where-Object { $_ -match "\|onlyoffice/documentserver" -and $_ -notmatch "^ada-elm-onlyoffice" }
  if (-not $rows) { return $null }
  $name, $image, $ports = ($rows | Select-Object -First 1) -split "\|", 3
  $port = if ($ports -match ":(\d+)->80/tcp") { $matches[1] } else { $null }
  $secret = (docker exec $name /var/www/onlyoffice/documentserver/npm/json -f /etc/onlyoffice/documentserver/local.json services.CoAuthoring.secret.session.string 2>$null | Out-String).Trim()
  $envs = (docker inspect $name --format "{{range .Config.Env}}{{println .}}{{end}}" 2>$null | Out-String)
  $priv = $envs -match "ALLOW_PRIVATE_IP_ADDRESS=true"
  if (-not $priv) {
    $cfg = (docker exec $name cat /etc/onlyoffice/documentserver/local.json 2>$null | Out-String)
    $priv = $cfg -match '"allowPrivateIPAddress"\s*:\s*true'
  }
  return @{ Name = $name; Image = $image; Port = $port; Secret = $secret; PrivateIpOk = $priv }
}

function EnsureEnv {
  if (Test-Path $EnvFile) { Ok ".env exists - keeping current configuration"; return }
  Step "First-run configuration"
  $default = [System.Net.Dns]::GetHostName()
  $hostIn = Read-Host "  Server name or IP that USERS will type in their browser [$default]"
  if (-not $hostIn) { $hostIn = $default }
  $port = Read-Host "  Web port for ADA-ELM [8088]"; if (-not $port) { $port = "8088" }

  # ---- OnlyOffice: reuse the one already running, or start the bundled one
  $mode = "bundled"; $ooPort = "8080"; $jwt = NewSecret 32
  $oo = FindExistingOnlyOffice
  if ($oo) {
    Write-Host "    Found running OnlyOffice: container '$($oo.Name)' ($($oo.Image)) on port $($oo.Port)" -ForegroundColor Yellow
    $use = Read-Host "  Use this existing OnlyOffice for ADA-ELM? Y/N [Y]"
    if ($use -notmatch "^[Nn]") {
      $mode = "existing"
      $ooPort = if ($oo.Port) { $oo.Port } else { Read-Host "  OnlyOffice host port" }
      if ($oo.Secret) { $jwt = $oo.Secret; Ok "JWT secret read from the OnlyOffice container" }
      else { $jwt = Read-Host "  Could not read the JWT secret automatically. Enter the OnlyOffice JWT secret (leave empty only if JWT is disabled)" }
      if (-not $oo.PrivateIpOk) {
        Warn "OnlyOffice '$($oo.Name)' does not allow private IP addresses. Editing/saving will fail with 'Download failed'."
        Warn "Fix: re-create that container with  -e ALLOW_PRIVATE_IP_ADDRESS=true  (keep its other options), then restart it."
      }
    }
  }
  if ($mode -eq "bundled") {
    if ($oo -and $oo.Port -eq "8080") { $ooPort = "8081" }   # avoid clashing with the OnlyOffice already on 8080
    $p = Read-Host "  Port for the bundled document editor (OnlyOffice) [$ooPort]"; if ($p) { $ooPort = $p }
  }
  $demo = Read-Host "  Load DEMO data (sample org, users, AMCA project)? Y/N [N]"
  $seedDemo = if ($demo -match "^[Yy]") { "true" } else { "false" }
  $adminPw = NewSecret 14
  if ($mode -eq "existing") {
    $profiles = ""; $ooInternal = "http://host.docker.internal:$ooPort"; $backendInternal = "http://host.docker.internal:$port"
  } else {
    $profiles = "bundled-onlyoffice"; $ooInternal = "http://onlyoffice"; $backendInternal = "http://web"
  }
  @(
    "# Generated by START-ADA-ELM on $(Get-Date -f s). Keep this file safe (contains secrets).",
    "ELM_ENVIRONMENT=uat",
    "ELM_SEED_DEMO_DATA=$seedDemo",
    "ELM_ADMIN_PASSWORD=$adminPw",
    "ELM_SERVER_HOST=$hostIn",
    "ELM_HTTP_PORT=$port",
    "ELM_DB_PASSWORD=$(NewSecret 24)",
    "ELM_SECRET_KEY=$(NewSecret 64)",
    "ELM_COOKIE_SECURE=false",
    "ELM_MAX_UPLOAD_MB=200",
    "# --- document editor ($mode OnlyOffice)",
    "ELM_ONLYOFFICE_MODE=$mode",
    "COMPOSE_PROFILES=$profiles",
    "ELM_ONLYOFFICE_PORT=$ooPort",
    "ELM_ONLYOFFICE_JWT_SECRET=$jwt",
    "ELM_ONLYOFFICE_PUBLIC_URL=http://${hostIn}:$ooPort",
    "ELM_ONLYOFFICE_INTERNAL_URL=$ooInternal",
    "ELM_BACKEND_INTERNAL_URL=$backendInternal"
  ) | Set-Content $EnvFile -Encoding ASCII
  $cred = if ($seedDemo -eq "true") { "Demo users: pe.kumar, chk.das, rev.joshi, td.menon, cm.sharma, pgd.rao, adm.babu, admin ... password Elm@12345" } else { "Administrator: username 'admin'  password '$adminPw'" }
  Set-Content (Join-Path $PSScriptRoot "ADMIN-CREDENTIALS.txt") "ADA-ELM initial sign-in`r`n$cred`r`nURL: http://${hostIn}:$port`r`nChange the password after first sign-in. Delete this file afterwards." -Encoding ASCII
  Ok "Configuration written to .env ($mode OnlyOffice; credentials in ADMIN-CREDENTIALS.txt)"
}

function CheckPorts($envh) {
  foreach ($p in @($envh["ELM_HTTP_PORT"], $envh["ELM_ONLYOFFICE_PORT"])) {
    $busy = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -and (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -notmatch "com.docker|docker|wslrelay|vpnkit" }
    if ($busy) { Fail "Port $p is already used by another program (PID $($busy[0].OwningProcess)). Change the port in .env and retry." }
  }
}

function OpenFirewall($envh) {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $ports = "$($envh['ELM_HTTP_PORT']),$($envh['ELM_ONLYOFFICE_PORT'])"
  if (-not $isAdmin) { Warn "Not running as Administrator - firewall not changed. Other PCs need inbound TCP $ports allowed (run START as Administrator once)."; return }
  if (-not (Get-NetFirewallRule -DisplayName "ADA-ELM" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "ADA-ELM" -Direction Inbound -Protocol TCP -LocalPort ($ports -split ",") -Action Allow -Profile Domain,Private | Out-Null
    Ok "Firewall rule 'ADA-ELM' created for TCP $ports"
  }
}

function WaitHttp($url, $what, $timeoutSec) {
  Write-Host "    ... waiting for $what" -NoNewline
  $t = 0
  while ($t -lt $timeoutSec) {
    try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 $url; if ($r.StatusCode -eq 200) { Write-Host ""; Ok "$what is up"; return $true } } catch {}
    Start-Sleep 5; $t += 5; Write-Host "." -NoNewline
  }
  Write-Host ""; Warn "$what not ready after $timeoutSec s (check: STATUS-ADA-ELM.bat / logs)"; return $false
}

# ---------------------------------------------------------------- actions
switch ($Action) {
  "start" {
    Add-Content $Log "`n===== START $(Get-Date -f s) ====="
    EnsureDocker
    VerifyPackage
    EnsureEnv
    LoadImages
    $envh = ReadEnv
    CheckPorts $envh
    OpenFirewall $envh
    Step "Starting ADA-ELM containers"
    Compose up -d --no-build --remove-orphans
    if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed. See: docker compose logs" }
    $base = "http://localhost:$($envh['ELM_HTTP_PORT'])"
    $okApp = WaitHttp "$base/api/health" "ADA-ELM application" 300
    $okOO  = WaitHttp "http://localhost:$($envh['ELM_ONLYOFFICE_PORT'])/healthcheck" "document editor (OnlyOffice, first start ~2-3 min)" 420
    Compose ps
    $url = "http://$($envh['ELM_SERVER_HOST']):$($envh['ELM_HTTP_PORT'])"
    Write-Host "`n  ADA-ELM is running:  $url" -ForegroundColor Green
    Write-Host "  First sign-in details: ADMIN-CREDENTIALS.txt (in this folder)`n" -ForegroundColor Green
    if ($okApp) { Start-Process "http://localhost:$($envh['ELM_HTTP_PORT'])" }
  }
  "stop"   { EnsureDocker; Step "Stopping ADA-ELM (data is kept)"; Compose stop; Ok "Stopped" }
  "status" { EnsureDocker; Compose ps; $envh = ReadEnv; WaitHttp "http://localhost:$($envh['ELM_HTTP_PORT'])/api/health" "ADA-ELM application" 10 | Out-Null }
  "logs"   { EnsureDocker; Compose logs --tail 200 backend web worker onlyoffice }
  "backup" {
    EnsureDocker
    $ts = Get-Date -f "yyyyMMdd-HHmmss"
    $dir = Join-Path $PSScriptRoot "backups\$ts"; New-Item -ItemType Directory $dir -Force | Out-Null
    Step "Backing up database"
    Compose exec -T db sh -c "pg_dump -U elm -d elm -Fc -f /tmp/elm.dump"; if ($LASTEXITCODE -ne 0) { Fail "pg_dump failed" }
    Compose cp db:/tmp/elm.dump (Join-Path $dir "elm-db.dump"); Ok "elm-db.dump"
    Step "Backing up document files and signing keys"
    docker run --rm -v ada-elm_elm-files:/data:ro -v "${dir}:/backup" postgres:16.6-alpine tar czf /backup/elm-files.tgz -C /data .
    if ($LASTEXITCODE -ne 0) { Fail "file backup failed" }
    Ok "elm-files.tgz"
    Copy-Item $EnvFile (Join-Path $dir "env.backup")
    Write-Host "`n  Backup complete: $dir  (store it on separate media)`n" -ForegroundColor Green
  }
}
