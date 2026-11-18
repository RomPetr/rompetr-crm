<#
.SYNOPSIS
    Configure Claude Code to use the DeepSeek Anthropic-compatible API.

.DESCRIPTION
    Reads ANTHROPIC_AUTH_TOKEN1 from .env, maps it to ANTHROPIC_AUTH_TOKEN, sets
    DeepSeek endpoint/model variables for the current user, and removes OAuth/API-key
    variables that would take precedence. The token itself is never printed.

.PARAMETER EnvFile
    Path to .env. Defaults to the repository root next to this script.

.PARAMETER SessionOnly
    Set variables only in the current PowerShell process, do not persist to the user profile.

.PARAMETER DryRun
    Parse .env and show what would change, without changing anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\setup-deepseek-env.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\setup-deepseek-env.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env'),
    [switch]$SessionOnly,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Файл .env не найден: $EnvFile"
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        $values[$name] = $value
    }
}

$token = $values['ANTHROPIC_AUTH_TOKEN1']
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'ANTHROPIC_AUTH_TOKEN1 не найден или пуст в .env'
}
if ($token.Length -lt 20) {
    throw "ANTHROPIC_AUTH_TOKEN1 слишком короткий: $($token.Length) символов"
}

$vars = [ordered]@{
    'ANTHROPIC_AUTH_TOKEN'            = $token
    'ANTHROPIC_BASE_URL'              = 'https://api.deepseek.com/anthropic'
    'ANTHROPIC_MODEL'                 = 'deepseek-flash'
    'ANTHROPIC_DEFAULT_SONNET_MODEL'  = 'deepseek-flash'
    'ANTHROPIC_DEFAULT_OPUS_MODEL'    = 'deepseek-flash'
    'ANTHROPIC_DEFAULT_HAIKU_MODEL'   = 'deepseek-flash'
    'CLAUDE_CODE_SUBAGENT_MODEL'      = 'deepseek-flash'
    'CLAUDE_CODE_EFFORT_LEVEL'        = 'max'
    'CLAUDE_CODE_AUTO_COMPACT_WINDOW' = '786432'
}
$remove = @('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')

if ($DryRun) {
    "Dry run: $EnvFile"
    "Token length: $($token.Length)"
    "Would set: $($vars.Keys -join ', ')"
    "Would remove: $($remove -join ', ')"
    'No changes made.'
    return
}

foreach ($name in $vars.Keys) {
    if (-not $SessionOnly) {
        [Environment]::SetEnvironmentVariable($name, $vars[$name], 'User')
    }
    Set-Item -Path "Env:$name" -Value $vars[$name]
}

foreach ($name in $remove) {
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    if (-not $SessionOnly) {
        [Environment]::SetEnvironmentVariable($name, $null, 'User')
    }
}

"Set: $($vars.Keys -join ', ')"
"Removed: $($remove -join ', ')"
"Token length: $($token.Length)"
if ($SessionOnly) {
    'Scope: current PowerShell session only.'
} else {
    'Scope: current session and user profile (new terminals will inherit it).'
}
'Open a new terminal, then run: claude -p "Reply with exactly OK" --model deepseek-flash --max-turns 1'
