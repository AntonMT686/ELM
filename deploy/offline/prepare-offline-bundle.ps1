<#
  ADA-ELM - build the OFFLINE package on a CONNECTED Windows machine (the development PC).
  Run from PowerShell in the repository root:
      powershell -ExecutionPolicy Bypass -File deploy\offline\prepare-offline-bundle.ps1
  Output: dist\ADA-ELM-Offline-<version>\  -> copy this whole folder to the offline server.
#>
param([string]$Version = "0.1.0", [switch]$SkipOnlyOffice)  # -SkipOnlyOffice: server already runs OnlyOffice (saves ~2.5 GB)
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Out  = Join-Path $Root "dist\ADA-ELM-Offline-$Version"
$Images = @(
  @{ Name = "ada-elm/backend:0.1.0";            File = "ada-elm-backend.tar" },
  @{ Name = "ada-elm/web:0.1.0";                File = "ada-elm-web.tar" },
  @{ Name = "postgres:16.6-alpine";             File = "postgres-16.6-alpine.tar" },
  @{ Name = "onlyoffice/documentserver:8.2.2";  File = "onlyoffice-documentserver-8.2.2.tar" }
)
if ($SkipOnlyOffice) { $Images = $Images | Where-Object { $_.Name -notlike "onlyoffice/*" } }

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }

Step "Checking Docker"
docker info --format "{{.OSType}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker engine is not running. Start Docker Desktop and retry." }

Step "Building application images (backend + web) - needs internet on THIS machine"
Push-Location $Root
if (-not (Test-Path "$Root\.env")) { Copy-Item "$Root\.env.example" "$Root\.env" }
$env:ELM_DB_PASSWORD = "build-only"
$env:ELM_DEMO_HINT = "0"
docker compose build backend web
if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }
Pop-Location

Step "Pulling third-party images"
docker pull postgres:16.6-alpine;            if ($LASTEXITCODE -ne 0) { throw "pull postgres failed" }
if (-not $SkipOnlyOffice) { docker pull onlyoffice/documentserver:8.2.2; if ($LASTEXITCODE -ne 0) { throw "pull onlyoffice failed" } }

Step "Creating package folder $Out"
if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Path "$Out\images" | Out-Null

foreach ($img in $Images) {
  Step "Saving $($img.Name)  (this can take a few minutes)"
  docker save -o (Join-Path "$Out\images" $img.File) $img.Name
  if ($LASTEXITCODE -ne 0) { throw "docker save failed for $($img.Name)" }
}

Step "Copying run scripts and configuration"
Copy-Item "$PSScriptRoot\docker-compose.offline.yml" "$Out\docker-compose.yml"
Copy-Item "$PSScriptRoot\elm.ps1", "$PSScriptRoot\START-ADA-ELM.bat", "$PSScriptRoot\STOP-ADA-ELM.bat", "$PSScriptRoot\STATUS-ADA-ELM.bat", "$PSScriptRoot\BACKUP-ADA-ELM.bat" $Out
Copy-Item "$Root\Docs\OFFLINE_DEPLOYMENT.md" "$Out\README-OFFLINE.md"
if (Test-Path "$PSScriptRoot\installers") {
  Step "Copying prerequisite installers (Docker Desktop, WSL)"
  Copy-Item "$PSScriptRoot\installers" "$Out\installers" -Recurse
} else {
  Write-Host "   NOTE: put 'Docker Desktop Installer.exe' and the WSL .msi in deploy\offline\installers\ to ship them too." -ForegroundColor Yellow
}

Step "Writing image list and SHA-256 checksums"
$Images | ForEach-Object { "$($_.Name)`t$($_.File)" } | Set-Content "$Out\images\IMAGES.txt" -Encoding ASCII
Get-ChildItem $Out -Recurse -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
  $rel = $_.FullName.Substring($Out.Length + 1)
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $rel
} | Set-Content "$Out\SHA256SUMS.txt" -Encoding ASCII

$size = "{0:N1} GB" -f ((Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB)
Write-Host "`nDONE. Package: $Out  ($size)" -ForegroundColor Green
Write-Host "Copy the WHOLE folder to the offline server and double-click START-ADA-ELM.bat" -ForegroundColor Green
