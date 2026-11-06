<#
  ADA-ELM backup on Windows: the ELM tables (elm_* only) of the ELM database, plus the file store (data\storage, data\pki).
      powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1 [-MysqlBin C:\xampp7410\mysql\bin] [-Target D:\ELM-backups]
  Connection details (user, password, host, port, database) are read from ELM_DATABASE_URL in .env. Any of them can be
  overridden: -User root -Port 3309 -DbHost 127.0.0.1 -Database proflow_uat. The password is asked for only when the
  URL has none and MYSQL_PWD is not set.
  Legacy PMS tables are not part of this backup; back them up with your usual database procedure.
  Restore: mysql -u <user> -p <database> < elm-db-<stamp>.sql   and unzip elm-files-<stamp>.zip into the ELM folder.
#>
param([string]$MysqlBin = "C:\xampp7410\mysql\bin", [string]$Target = "", [string]$User = "", [string]$Port = "", [string]$DbHost = "", [string]$Database = "")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Target) { $Target = Join-Path $Root "backups" }
$mysql = Join-Path $MysqlBin "mysql.exe"; $dump = Join-Path $MysqlBin "mysqldump.exe"
if (-not (Test-Path $dump)) { throw "mysqldump.exe not found in $MysqlBin. Pass the right folder with -MysqlBin." }

# ---- read ELM_DATABASE_URL from .env (last non-comment line wins, quotes and spaces removed)
$envFile = Join-Path $Root ".env"
$url = ""
if (Test-Path $envFile) {
  $line = Get-Content $envFile | Where-Object { $_ -match '^\s*ELM_DATABASE_URL\s*=' } | Select-Object -Last 1
  if ($line) { $url = ($line -replace '^\s*ELM_DATABASE_URL\s*=\s*', '').Trim().Trim('"').Trim("'") }
}
$urlPassword = $null
if ($url) {
  $m = [regex]::Match($url, '^mysql(\+\w+)?://(?<user>[^:@/]+)(:(?<pw>[^@]*))?@(?<host>[^:/?]+)(:(?<port>\d+))?/(?<db>[^?]+)')
  if (-not $m.Success) { throw "Could not read ELM_DATABASE_URL in $envFile ($url). Expected mysql+pymysql://user:password@host:port/database?charset=utf8mb4, or pass -User -Port -Database." }
  if (-not $User) { $User = $m.Groups["user"].Value }
  if (-not $DbHost) { $DbHost = $m.Groups["host"].Value }
  if (-not $Port) { $Port = $m.Groups["port"].Value }
  if (-not $Database) { $Database = $m.Groups["db"].Value }
  if ($m.Groups["pw"].Success) { $urlPassword = [uri]::UnescapeDataString($m.Groups["pw"].Value) }
}
if (-not $User) { $User = "root" }; if (-not $DbHost) { $DbHost = "127.0.0.1" }; if (-not $Port) { $Port = "3306" }
if (-not $Database) { throw "No database name: set ELM_DATABASE_URL in .env or pass -Database." }
Write-Host "Database: $User@$DbHost`:$Port/$Database" -ForegroundColor Cyan

if ($null -ne $urlPassword) { $env:MYSQL_PWD = $urlPassword }
elseif (-not $env:MYSQL_PWD) {
  $sec = Read-Host "MySQL password for $User (press Enter if none)" -AsSecureString
  $env:MYSQL_PWD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

# ---- check the connection first, so the real problem is reported
$tables = & $mysql --host=$DbHost --port=$Port --user=$User -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$Database' AND table_name LIKE 'elm\_%'" 2>&1
if ($LASTEXITCODE -ne 0) {
  throw "Cannot connect to MySQL at $DbHost`:$Port as $User. Is MySQL started (XAMPP Control Panel) and is the port right? MySQL said: $tables"
}
$tables = @($tables | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
if (-not $tables.Count) { throw "Connected, but database $Database has no elm_* tables. Check the database name in ELM_DATABASE_URL." }

New-Item -ItemType Directory -Force -Path $Target | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sql = Join-Path $Target "elm-db-$stamp.sql"
& $dump --host=$DbHost --port=$Port --user=$User --single-transaction --skip-triggers --default-character-set=utf8mb4 "--result-file=$sql" $Database @tables
if ($LASTEXITCODE -ne 0) { throw "mysqldump failed" }
$zip = Join-Path $Target "elm-files-$stamp.zip"
$data = Join-Path $Root "data"
if (Test-Path $data) { Compress-Archive -Path $data -DestinationPath $zip }
$sums = Join-Path $Target "elm-$stamp.sha256"
"{0}  {1}" -f (Get-FileHash $sql -Algorithm SHA256).Hash, (Split-Path $sql -Leaf) | Set-Content $sums
if (Test-Path $zip) { "{0}  {1}" -f (Get-FileHash $zip -Algorithm SHA256).Hash, (Split-Path $zip -Leaf) | Add-Content $sums }
Write-Host "Backup of $($tables.Count) ELM tables written to $Target ($stamp)" -ForegroundColor Green
