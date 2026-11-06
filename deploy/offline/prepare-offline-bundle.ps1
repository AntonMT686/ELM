<#
  ADA-ELM - build the OFFLINE package on a CONNECTED Windows x64 PC (same OS family and CPU as the offline server).
  Run from PowerShell in the repository folder:
      powershell -ExecutionPolicy Bypass -File deploy\offline\prepare-offline-bundle.ps1
  Options:
      -Version 0.2.0          package version label
      -PythonVersion 3.12     must match the Python that will be installed on the offline server
      -IncludeOnlyOffice      also save the OnlyOffice Docker image (needs Docker on this PC; ~2.5 GB)
      -IncludeDrawio          also save the jgraph/drawio Docker image for the embedded diagram editor (~0.5 GB)
  Output: dist\ADA-ELM-Offline-<version>\  -> copy the whole folder to the offline server and follow README-OFFLINE.md.

  The application itself does NOT run in Docker. The package holds the source, the Python wheels, the npm cache,
  the built frontend, the installers you put in deploy\offline\installers\, and optional container images.
#>
param([string]$Version = "0.2.0", [string]$PythonVersion = "3.12", [switch]$IncludeOnlyOffice, [switch]$IncludeDrawio)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Out = Join-Path $Root "dist\ADA-ELM-Offline-$Version"
function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" } }

Step "Checking tools on this (connected) PC"
Need py "Install Python $PythonVersion (64-bit) with the py launcher."
Need node "Install Node.js 22 LTS (64-bit)."
Need npm "Install Node.js 22 LTS (64-bit)."
& py "-$PythonVersion" --version; if ($LASTEXITCODE -ne 0) { throw "Python $PythonVersion is not installed on this PC." }
if ($IncludeOnlyOffice -or $IncludeDrawio) { Need docker "Docker is needed only to save the optional images." }

Step "Creating $Out"
if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Path "$Out\offline\wheels", "$Out\offline\npm-cache", "$Out\offline\images" | Out-Null

Step "Copying the application source (without caches, data, secrets)"
$exclude = @("node_modules", ".venv", "__pycache__", "data", "dist", "logs", ".git", "_to_delete", "offline")
robocopy $Root "$Out" /E /XD $exclude /XF ".env" "*.db" "*.pyc" "pms_bundle*.json*" /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
Copy-Item "$Root\Docs\OFFLINE_DEPLOYMENT.md" "$Out\README-OFFLINE.md"

Step "Downloading Python wheels for Windows x64 / Python $PythonVersion"
& py "-$PythonVersion" -m pip download --disable-pip-version-check -r "$Root\backend\requirements.txt" -d "$Out\offline\wheels" --only-binary=:all: --platform win_amd64 --python-version $PythonVersion --implementation cp
if ($LASTEXITCODE -ne 0) { throw "pip download failed" }
& py "-$PythonVersion" -m pip download --disable-pip-version-check pip setuptools wheel -d "$Out\offline\wheels" --only-binary=:all: --platform win_amd64 --python-version $PythonVersion --implementation cp
if ($LASTEXITCODE -ne 0) { throw "pip download (pip/setuptools) failed" }

Step "Filling the npm cache and building the frontend"
Push-Location "$Out\frontend"
try {
  npm ci --no-audit --no-fund --cache "$Out\offline\npm-cache"
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
  $env:VITE_DEMO_HINT = "0"
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
  # node_modules is rebuilt on the server from the cache (setup.ps1 -Offline), which keeps the package small and clean.
  Remove-Item node_modules -Recurse -Force
} finally { Pop-Location }

if ($IncludeOnlyOffice) {
  Step "Saving the OnlyOffice image"
  docker pull onlyoffice/documentserver:8.2.2; if ($LASTEXITCODE -ne 0) { throw "docker pull onlyoffice failed" }
  docker save -o "$Out\offline\images\onlyoffice-documentserver-8.2.2.tar" onlyoffice/documentserver:8.2.2
}
if ($IncludeDrawio) {
  Step "Saving the draw.io image"
  docker pull jgraph/drawio:24.7.17; if ($LASTEXITCODE -ne 0) { throw "docker pull drawio failed" }
  docker save -o "$Out\offline\images\drawio-24.7.17.tar" jgraph/drawio:24.7.17
}

if (Test-Path "$PSScriptRoot\installers") {
  Step "Copying prerequisite installers"
  Copy-Item "$PSScriptRoot\installers" "$Out\offline\installers" -Recurse
}

Step "Writing SHA-256 checksums"
Get-ChildItem $Out -Recurse -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($Out.Length + 1)
} | Set-Content "$Out\SHA256SUMS.txt" -Encoding ASCII

$size = "{0:N2} GB" -f ((Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB)
Write-Host "`nDONE: $Out ($size)" -ForegroundColor Green
Write-Host "Copy the whole folder to the offline server, then follow README-OFFLINE.md, section 4." -ForegroundColor Green
