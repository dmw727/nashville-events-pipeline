param([switch]$Offline, [string]$AsOf, [int]$Days=42, [string]$Sources)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) { & $pyLauncher.Source -3 -m venv .venv }
    elseif ($pythonCommand) { & $pythonCommand.Source -m venv .venv }
    else { throw 'Python 3.11 or newer is required. Install Python, then run this script again.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $pythonPath -c "import bs4, dateutil, icalendar, recurring_ical_events, tzdata" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Run .venv\Scripts\python.exe -m pip install -r requirements.txt and retry.' }
}
$env:PYTHONIOENCODING = 'utf-8'
$arguments = @('-m','nashville_weekly','--days',"$Days")
if ($Offline) { $arguments += '--offline' }
if ($AsOf) { $arguments += @('--as-of',$AsOf) }
if ($Sources) { $arguments += @('--sources',$Sources) }
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logPath = Join-Path $PSScriptRoot ('logs\run-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
& $pythonPath @arguments 2>&1 | Tee-Object -FilePath $logPath
$result = $LASTEXITCODE
if ($result -eq 2) { Write-Host 'Report created with coverage warnings. Open report.html for source health.' }
exit $result
