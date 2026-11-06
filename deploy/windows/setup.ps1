<#
  ADA-ELM one-time setup on Windows (no Docker for the application).
  Run from the repository folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1
  Options:
      -Offline        install only from the offline package (offline\wheels, offline\npm-cache); never use the internet
      -RebuildFrontend  rebuild frontend\dist even if it exists
      -SkipDatabase   do not create/upgrade the ELM tables in proflow_uat now

  It is safe to run again (after an update, for example): existing .env, data and database rows are kept.
#>
param([switch]$Offline, [switch]$RebuildFrontend, [switch]$SkipDatabase)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Wheels = Join-Path $Root "offline\wheels"
$NpmCache = Join-Path $Root "offline\npm-cache"
if (-not $Offline -and (Test-Path $Wheels)) { $Offline = $true }

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    !!  $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host "`n    XX  $t`n" -ForegroundColor Red; exit 1 }
function NewSecret([int]$n = 64) {
  $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
  $bytes = New-Object byte[] $n
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

# ------------------------------------------------------------------ prerequisites
Step "Checking prerequisites"
$Py = $null
foreach ($cand in @(@("py", "-3.12"), @("py", "-3.11"), @("py", "-3.13"), @("python"))) {
  try {
    $v = & $cand[0] $cand[1..($cand.Length - 1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.11") { $Py = $cand; break }
  } catch { }
}
if (-not $Py) { Fail "Python 3.11 or newer was not found. Install Python 3.12 (64-bit) with 'Add python.exe to PATH' ticked." }
Ok "Python $v ($($Py -join ' '))"
$node = (Get-Command node -ErrorAction SilentlyContinue)
if (-not $node) { Fail "Node.js was not found. Install Node.js 22 LTS (64-bit)." }
$nv = (& node --version).TrimStart("v")
if ([version]$nv -lt [version]"20.0") { Fail "Node.js $nv is too old. Install Node.js 22 LTS." }
Ok "Node.js $nv"
if ($Offline) { Ok "Offline mode: packages come from $Root\offline" }

# ------------------------------------------------------------------ configuration
Step "Configuration (.env)"
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
  Ok ".env exists - keeping it"
} else {
  $text = Get-Content (Join-Path $Root ".env.example") -Raw
  $text = $text -replace "ELM_SECRET_KEY=.*", ("ELM_SECRET_KEY=" + (NewSecret 64))
  Set-Content -Path $EnvFile -Value $text -Encoding ASCII
  Warn ".env created from .env.example. Edit ELM_DATABASE_URL, the OnlyOffice and GitLab values, then run this script again."
  notepad $EnvFile
  exit 0
}

# ------------------------------------------------------------------ backend
Step "Backend: Python virtual environment"
$Venv = Join-Path $Backend ".venv"
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) { & $Py[0] $Py[1..($Py.Length - 1)] -m venv $Venv; if ($LASTEXITCODE -ne 0) { Fail "Could not create $Venv" } }
if ($Offline) {
  & $VPy -m pip install --no-index --find-links $Wheels -r (Join-Path $Backend "requirements.txt")
} else {
  & $VPy -m pip install --disable-pip-version-check -r (Join-Path $Backend "requirements.txt")
}
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see the messages above)" }
Ok "Backend packages installed"

# ------------------------------------------------------------------ frontend
Step "Frontend: Node packages and production build"
Push-Location $Frontend
try {
  if (-not (Test-Path "node_modules")) {
    if ($Offline) { npm ci --offline --no-audit --no-fund --cache $NpmCache } else { npm ci --no-audit --no-fund }
    if ($LASTEXITCODE -ne 0) { Fail "npm ci failed (see the messages above)" }
  }
  if ($RebuildFrontend -or -not (Test-Path "dist\index.html")) {
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail "Frontend build failed" }
  }
  Ok "Frontend ready (frontend\dist)"
} finally { Pop-Location }

# ------------------------------------------------------------------ database
if (-not $SkipDatabase) {
  Step "Database: ELM tables in proflow_uat (elm_* only; legacy tables are not touched)"
  Push-Location $Backend
  try {
    & $VPy -m app.dbsetup
    if ($LASTEXITCODE -ne 0) { Fail "Database setup failed. Check ELM_DATABASE_URL in .env and that MySQL/MariaDB is running (XAMPP Control Panel)." }
  } finally { Pop-Location }
  Ok "Database ready"
}

Write-Host "`nSetup complete. Start ADA-ELM with deploy\windows\start-all.bat" -ForegroundColor Green
