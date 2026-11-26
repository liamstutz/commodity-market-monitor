param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$monitorRoot = $PSScriptRoot
$monitorUrl = "http://127.0.0.1:8766/"
$monitorPython = $null
$monitorCandidates = @()
if ($env:CODEX_PRIMARY_RUNTIME_PYTHON) { $monitorCandidates += $env:CODEX_PRIMARY_RUNTIME_PYTHON }
$monitorNode = Get-Command node -ErrorAction SilentlyContinue
if ($monitorNode) {
    $monitorRuntime = Split-Path (Split-Path (Split-Path $monitorNode.Source))
    $monitorCandidates += Join-Path $monitorRuntime "python\python.exe"
}
$monitorCommand = Get-Command python -ErrorAction SilentlyContinue
if ($monitorCommand) { $monitorCandidates += $monitorCommand.Source }
foreach ($monitorCandidate in ($monitorCandidates | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $monitorCandidate) {
        & $monitorCandidate -c "import sys; from zoneinfo import ZoneInfo; ZoneInfo('America/New_York'); assert sys.version_info >= (3, 10)" 2>$null
        if ($LASTEXITCODE -eq 0) { $monitorPython = $monitorCandidate; break }
    }
}
if (-not $monitorPython) { throw "Python 3.10+ with time-zone data is required. Install Python, then run: python -m pip install tzdata" }
$monitorRunning = $false
try {
    $monitorHealth = Invoke-RestMethod -Uri ($monitorUrl + "api/health") -TimeoutSec 2
    if ($monitorHealth.service -eq "commodity-monitor-intraday-v1") { $monitorRunning = $true }
    else { throw "Another service is using port 8766." }
} catch { if ($_.Exception.Message -like "*Another service*") { throw } }
if (-not $monitorRunning) {
    $monitorLogDir = Join-Path $monitorRoot ".private"
    New-Item -ItemType Directory -Path $monitorLogDir -Force | Out-Null
    $monitorScript = Join-Path $monitorRoot "pipeline\intraday_server.py"
    $monitorProcess = Start-Process -FilePath $monitorPython -ArgumentList @('"' + $monitorScript + '"') -WorkingDirectory $monitorRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $monitorLogDir "collector.out.log") -RedirectStandardError (Join-Path $monitorLogDir "collector.err.log") -PassThru
    for ($monitorAttempt = 0; $monitorAttempt -lt 50; $monitorAttempt++) {
        try {
            $monitorHealth = Invoke-RestMethod -Uri ($monitorUrl + "api/health") -TimeoutSec 1
            if ($monitorHealth.service -eq "commodity-monitor-intraday-v1") { $monitorRunning = $true; break }
        } catch {}
        if ($monitorProcess.HasExited) { break }
        Start-Sleep -Milliseconds 200
    }
}
if (-not $monitorRunning) { throw "Collector did not start. See .private\collector.err.log." }
Write-Output "Private intraday monitor: $monitorUrl"
Write-Output "Refreshes every five minutes while this computer is awake. Stop it using the dashboard button."
if (-not $NoBrowser) { Start-Process $monitorUrl }
