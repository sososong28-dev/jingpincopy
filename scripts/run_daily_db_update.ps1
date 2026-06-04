$ErrorActionPreference = "Stop"

$ScriptPath = $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptPath)
Set-Location $Root

$Python = $env:KIN_PYTHON
if (-not $Python) {
    $Candidate = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $Candidate) {
        $Python = $Candidate
    } else {
        $Python = "python"
    }
}

$LogDir = Join-Path $Root "outputs\automation"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Date = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "$Date-db-update.log"

& $Python "scripts\run_collector.py" --max-items 30 --no-email *>&1 | Tee-Object -FilePath $LogFile
exit $LASTEXITCODE
