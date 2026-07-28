$ErrorActionPreference = "Stop"

$ScriptPath = $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptPath)
Set-Location $Root

$Npx = "npx.cmd"
$NodeModules = Join-Path $Root "node_modules\playwright"
if (-not (Test-Path -Path $NodeModules)) {
    $env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
    & npm.cmd install
}

& node "scripts\social_browser_collect.mjs" @args
exit $LASTEXITCODE
