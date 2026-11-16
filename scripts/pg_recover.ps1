﻿#Requires -RunAsAdministrator
# Восстанавливает суперпользователя postgres и роль rompetr_app.
# Запускать в PowerShell от имени администратора:
#   powershell -ExecutionPolicy Bypass -File scripts\pg_recover.ps1

$ErrorActionPreference = "Stop"

$PgBin = "C:\Program Files\PostgreSQL\16\bin"
$DataDir = "C:\Program Files\PostgreSQL\16\data"
$Service = "postgresql-x64-16"

if (-not (Test-Path "$PgBin\postgres.exe")) {
    throw "Не найден $PgBin\postgres.exe"
}
if (-not (Test-Path "$DataDir\PG_VERSION")) {
    throw "Не найден каталог данных $DataDir"
}

$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (-not (Test-Path $envFile)) {
    throw "Не найден .env. Сначала scripts\migrate_env.py"
}

$dbLine = Get-Content $envFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
if (-not $dbLine) { throw "DATABASE_URL не найден в .env" }
$dbUrl = $dbLine.Substring("DATABASE_URL=".Length)
if ($dbUrl -notmatch '://[^:]+:([^@]+)@') { throw "Не удалось разобрать DATABASE_URL" }
$appPass = [Uri]::UnescapeDataString($Matches[1])
if ($appPass -eq "change-me") { throw "В .env остался пароль change-me" }

$secure = Read-Host "Новый пароль для роли postgres" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $pgPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

function Escape-Sql([string]$value) { return $value.Replace("'", "''") }

$sql = @"
DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_authid WHERE rolname = 'postgres') THEN CREATE ROLE postgres SUPERUSER LOGIN; END IF; END `$`$;
ALTER ROLE postgres WITH SUPERUSER LOGIN PASSWORD '$(Escape-Sql $pgPass)';
DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_authid WHERE rolname = 'rompetr_app') THEN CREATE ROLE rompetr_app LOGIN; END IF; END `$`$;
ALTER ROLE rompetr_app WITH LOGIN PASSWORD '$(Escape-Sql $appPass)';
SELECT rolname FROM pg_authid ORDER BY 1;
"@

$tmp = Join-Path $env:TEMP "pg_recover.sql"
[IO.File]::WriteAllText($tmp, $sql, (New-Object Text.UTF8Encoding $false))

Write-Host "Останавливаю службу $Service..."
Stop-Service -Name $Service -Force

try {
    Write-Host "Запускаю single-user режим..."
    Get-Content -Path $tmp -Encoding UTF8 | & "$PgBin\postgres.exe" --single -D $DataDir postgres
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "postgres --single завершился с кодом $LASTEXITCODE"
    }
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Write-Host "Запускаю службу $Service..."
    Start-Service -Name $Service
}

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Готово. Проверка подключения:"
try {
    $env:PGPASSWORD = $pgPass
    & "$PgBin\psql.exe" -U postgres -d postgres -c "select current_user, version();" 2>&1 | Select-Object -First 3
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host ""
Write-Host "Дальше: .venv\Scripts\python.exe scripts\init_db.py"
