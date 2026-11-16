# PostgreSQL recovery: temporarily allow local trust auth, find an existing
# superuser, create/update postgres and rompetr_app, restore scram auth.
# Run in an elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\pg_recover.ps1

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$PgBin = "C:\Program Files\PostgreSQL\16\bin"
$DataDir = "C:\Program Files\PostgreSQL\16\data"
$Service = "postgresql-x64-16"
$Hba = Join-Path $DataDir "pg_hba.conf"

if (-not (Test-Path "$PgBin\psql.exe")) { throw "psql.exe not found in $PgBin" }
if (-not (Test-Path $Hba)) { throw "pg_hba.conf not found in $DataDir" }

$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (-not (Test-Path $envFile)) { throw ".env not found. Run scripts\migrate_env.py first." }

$dbLine = Get-Content $envFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
if (-not $dbLine) { throw "DATABASE_URL not found in .env" }
$dbUrl = $dbLine.Substring("DATABASE_URL=".Length)
if ($dbUrl -notmatch '://[^:]+:([^@]+)@') { throw "Cannot parse DATABASE_URL" }
$appPass = [Uri]::UnescapeDataString($Matches[1])
if ($appPass -eq "change-me") { throw "DATABASE_URL still contains change-me" }

$secure = Read-Host "New password for the postgres role" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $pgPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

function Escape-Sql([string]$value) { return $value.Replace("'", "''") }

$original = [IO.File]::ReadAllText($Hba)
$trustRules = "host all all 127.0.0.1/32 trust`r`nhost all all ::1/128 trust`r`n"

function Reload-Postgres {
    & "$PgBin\pg_ctl.exe" reload -D $DataDir 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

try {
    [IO.File]::WriteAllText($Hba, $trustRules + $original, (New-Object Text.UTF8Encoding $false))
    Reload-Postgres

    $candidates = @(
        "NetworkService",
        "NT AUTHORITY\NetworkService",
        "NT AUTHORITY\SYSTEM",
        "NT SERVICE\postgresql-x64-16",
        "postgresql-x64-16",
        "postgres",
        "rp",
        "Administrator",
        "SYSTEM",
        $env:USERNAME,
        "$env:USERDOMAIN\$env:USERNAME"
    ) | Select-Object -Unique

    $super = $null
    $previousEa = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        foreach ($candidate in $candidates) {
            $isSuper = & "$PgBin\psql.exe" -w -h 127.0.0.1 -U $candidate -d postgres -tAc `
                "select rolsuper from pg_roles where rolname = current_user" 2>$null
            if ($LASTEXITCODE -eq 0 -and $isSuper -and $isSuper.Trim() -eq "t") {
                $super = $candidate
                break
            }
        }
    } finally {
        $ErrorActionPreference = $previousEa
    }

    if (-not $super) {
        $roles = & "$PgBin\psql.exe" -w -h 127.0.0.1 -U postgres -d postgres -tAc `
            "select rolname from pg_authid order by 1" 2>$null
        throw "No superuser role found among candidates. Roles visible: $roles"
    }
    Write-Host "Connected as superuser: $super"

    $sql = @"
DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_authid WHERE rolname = 'postgres') THEN CREATE ROLE postgres SUPERUSER LOGIN; END IF; END `$`$;
ALTER ROLE postgres WITH SUPERUSER LOGIN PASSWORD '$(Escape-Sql $pgPass)';
DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_authid WHERE rolname = 'rompetr_app') THEN CREATE ROLE rompetr_app LOGIN; END IF; END `$`$;
ALTER ROLE rompetr_app WITH LOGIN PASSWORD '$(Escape-Sql $appPass)';
"@
    $tmp = Join-Path $env:TEMP "pg_recover.sql"
    [IO.File]::WriteAllText($tmp, $sql, (New-Object Text.UTF8Encoding $false))

    try {
        & "$PgBin\psql.exe" -w -h 127.0.0.1 -v ON_ERROR_STOP=1 -U $super -d postgres -f $tmp
        if ($LASTEXITCODE -ne 0) { throw "psql failed with exit code $LASTEXITCODE" }
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
} finally {
    [IO.File]::WriteAllText($Hba, $original, (New-Object Text.UTF8Encoding $false))
    Reload-Postgres
}

Write-Host ""
Write-Host "Done. Verifying connection as postgres:"
try {
    $env:PGPASSWORD = $pgPass
    & "$PgBin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -tAc "select current_user"
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host ""
Write-Host "Next: .venv\Scripts\python.exe scripts\init_db.py"
