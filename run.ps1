param(
    [ValidateSet('start', 'verify', 'prepare', 'seed-large')]
    [string]$Command = 'start',
    [int]$Port = 8765,
    [string]$Database = ''
)
$ErrorActionPreference = 'Stop'
$candidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    'python', 'python3'
)
$selectedPython = $null
foreach ($candidate in $candidates) {
    $resolvedCommand = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue
    if ($resolvedCommand -and $resolvedCommand.Source -notlike '*\WindowsApps\*') {
        & $resolvedCommand.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
        if ($LASTEXITCODE -eq 0) { $selectedPython = $resolvedCommand.Source; break }
    }
}
if (-not $selectedPython) { throw 'Install Python 3.12+ and add it to PATH.' }
$scriptArguments = @((Join-Path $PSScriptRoot 'run.py'), $Command, '--port', [string]$Port)
if ($Database) { $scriptArguments += @('--database', $Database) }
& $selectedPython @scriptArguments
exit $LASTEXITCODE
