<#
.SYNOPSIS
    Run AutoSkill on this machine: the API, the frontend, and the background worker when the
    configuration asks for one.

.DESCRIPTION
    Starts every component in this console. Ctrl+C stops all of them, and if one dies the others
    are shut down rather than left pretending the stack is up.

    Run .\install.ps1 first. Works on Windows PowerShell 5.1 and on PowerShell 7.

.PARAMETER BackendOnly
    API (and worker) without the frontend dev server.

.PARAMETER FrontendOnly
    Frontend dev server alone, proxying to an API you started elsewhere.

.PARAMETER Worker
    Start the arq worker even if the configuration does not ask for it.

.PARAMETER NoWorker
    Never start the arq worker.

.PARAMETER ApiPort
    Default 8000.

.PARAMETER WebPort
    Default 5173.

.PARAMETER NoReload
    Do not restart the API when a Python file changes.

.PARAMETER Venv
    Defaults to .\.venv next to this script.

.EXAMPLE
    .\start.ps1

.EXAMPLE
    .\start.ps1 -BackendOnly -ApiPort 9000
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$Worker,
    [switch]$NoWorker,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [switch]$NoReload,
    [string]$Venv
)

$ErrorActionPreference = 'Stop'
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) { $PSNativeCommandUseErrorActionPreference = $false }

$Root = $PSScriptRoot
if (-not $Venv) { $Venv = Join-Path $Root '.venv' }
$onWindows = if (Test-Path Variable:IsWindows) { $IsWindows } else { $true }

$binDir = Join-Path $Venv 'Scripts'
if (-not (Test-Path $binDir)) { $binDir = Join-Path $Venv 'bin' }
$py = Join-Path $binDir 'python.exe'
if (-not (Test-Path $py)) { $py = Join-Path $binDir 'python' }
if (-not (Test-Path $py)) { throw "No virtualenv at $Venv - run .\install.ps1 first." }

$wantBackend = -not $FrontendOnly
$wantFrontend = -not $BackendOnly

# The worker only earns its process when jobs actually go to Redis.
$wantWorker = $false
if ($wantBackend) {
    $envFile = Join-Path $Root 'backend\.env'
    $configured = (Test-Path $envFile) -and ((Get-Content $envFile) -match '^\s*AUTOSKILL_JOBS\s*=\s*arq')
    $wantWorker = ($Worker -or $configured) -and -not $NoWorker
}

$started = @()

function Start-Component {
    param([string]$Label, [string]$Exe, [string[]]$Arguments, [string]$WorkDir)
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $WorkDir -NoNewWindow -PassThru
    Write-Host "==> $Label" -ForegroundColor Cyan -NoNewline
    Write-Host "  (pid $($process.Id))"
    return [pscustomobject]@{ Label = $Label; Process = $process }
}

try {
    if ($wantBackend) {
        $uvicorn = @('-m', 'uvicorn', 'autoskill.main:app', '--port', "$ApiPort")
        if (-not $NoReload) { $uvicorn += '--reload' }
        $started += Start-Component -Label "API      http://localhost:$ApiPort  (docs at /docs)" `
            -Exe $py -Arguments $uvicorn -WorkDir (Join-Path $Root 'backend')
    }
    if ($wantWorker) {
        $started += Start-Component -Label 'worker   arq' `
            -Exe $py -Arguments @('-m', 'autoskill.worker') -WorkDir (Join-Path $Root 'backend')
    }
    if ($wantFrontend) {
        $npm = 'npm'
        if ($onWindows -and (Get-Command 'npm.cmd' -ErrorAction SilentlyContinue)) { $npm = 'npm.cmd' }
        if (-not (Get-Command $npm -ErrorAction SilentlyContinue)) {
            throw 'npm not found - run .\install.ps1, or use -BackendOnly.'
        }
        if (-not (Test-Path (Join-Path $Root 'frontend\node_modules'))) {
            throw 'frontend\node_modules is missing - run .\install.ps1.'
        }
        $started += Start-Component -Label "UI       http://localhost:$WebPort" `
            -Exe $npm -Arguments @('run', 'dev', '--', '--port', "$WebPort") -WorkDir (Join-Path $Root 'frontend')
    }
    if ($started.Count -eq 0) { throw 'Nothing to start.' }

    Write-Host "`nCtrl+C stops everything.`n"

    # Poll instead of Wait-Process: that one waits for *all* of them, and a crashed API behind a
    # running UI is exactly the state this is meant to avoid.
    while ($true) {
        Start-Sleep -Milliseconds 500
        $dead = $started | Where-Object { $_.Process.HasExited }
        if ($dead) {
            # Windows PowerShell leaves ExitCode empty for a process killed from outside.
            $code = $dead[0].Process.ExitCode
            $how = if ($null -ne $code -and "$code" -ne '') { " (exit $code)" } else { '' }
            Write-Host "`n$($dead[0].Label) stopped$how - shutting the others down" -ForegroundColor Yellow
            break
        }
    }
} finally {
    foreach ($component in $started) {
        if ($component.Process.HasExited) { continue }
        # The whole tree, not just the process we started: `npm` is a launcher, and killing it
        # would leave the vite server it spawned holding the port.
        try {
            $ErrorActionPreference = 'SilentlyContinue'
            if ($onWindows) {
                & taskkill.exe /PID $component.Process.Id /T /F 2>&1 | Out-Null
            } else {
                Stop-Process -Id $component.Process.Id -Force
            }
        } catch { }
    }
}
