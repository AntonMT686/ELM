<#
  ADA-ELM backup on Windows: the ELM tables of proflow_uat (elm_* only) plus the file store (data\storage, data\pki).
      powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1 [-MysqlBin C:\xampp7410\mysql\bin] [-Target D:\ELM-backups]
  The database password is asked for (or taken from MYSQL_PWD). Legacy PMS tables are not part of this backup;
  back them up with your usual proflow_uat procedure.
  Restore: mysql -u <user> -p proflow_uat < elm-db-<stamp>.sql   and unzip elm-files-<stamp>.zip into the repository folder.
#>
param([string]$MysqlBin = "C:\xampp7410\mysql\bin", [string]$Target = "", [string]$User = "", [string]$Port = "", [string]$Database = "proflow_uat")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Target) { $Target = Join-Path $Root "backups" }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$envFile = Join-Path $Root ".env"
$url = (Get-Content $envFile | Where-Object { $_ -match "^ELM_DATABASE_URL=" }) -replace "^ELM_DATABASE_URL=", ""
if ($url -match "mysql\+pymysql://([^:]+):[^@]*@([^:/]+):?(\d+)?/([^?]+)") {
  if (-not $User) { $User = $Matches[1] }; $DbHost = $Matches[2]; if (-not $Port) { $Port = if ($Matches[3]) { $Matches[3] } else { "3306" } }; $Database = $Matches[4]
} else { $DbHost = "127.0.0.1"; if (-not $Port) { $Port = "3306" } }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$mysql = Join-Path $MysqlBin "mysql.exe"; $dump = Join-Path $MysqlBin "mysqldump.exe"
if (-not (Test-Path $dump)) { throw "mysqldump.exe not found in $MysqlBin (use -MysqlBin)." }
if (-not $env:MYSQL_PWD) { $sec = Read-Host "MySQL password for $User" -AsSecureString; $env:MYSQL_PWD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }
$tables = & $mysql -h $DbHost -P $Port -u $User -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$Database' AND table_name LIKE 'elm\_%'"
if (-not $tables) { throw "No elm_* tables found in $Database." }
$sql = Join-Path $Target "elm-db-$stamp.sql"
& $dump -h $DbHost -P $Port -u $User --single-transaction --routines=false --triggers=false --default-character-set=utf8mb4 $Database @($tables -split "\s+") --result-file=$sql
if ($LASTEXITCODE -ne 0) { throw "mysqldump failed" }
$zip = Join-Path $Target "elm-files-$stamp.zip"
$paths = @("data") | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path $_ }
if ($paths) { Compress-Archive -Path $paths -DestinationPath $zip }
"{0}  {1}" -f (Get-FileHash $sql -Algorithm SHA256).Hash, (Split-Path $sql -Leaf) | Set-Content (Join-Path $Target "elm-$stamp.sha256")
if (Test-Path $zip) { "{0}  {1}" -f (Get-FileHash $zip -Algorithm SHA256).Hash, (Split-Path $zip -Leaf) | Add-Content (Join-Path $Target "elm-$stamp.sha256") }
Write-Host "Backup written to $Target ($stamp)" -ForegroundColor Green
