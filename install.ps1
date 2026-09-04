<#
.SYNOPSIS
    Install every component of AutoSkill on this machine.

.DESCRIPTION
    Creates the backend virtualenv and installs the API, the `autoskill-local` CLI + companion
    MCP, the optional llmswitch provider library, applies the database migrations, builds the
    wheel the server hands to agents, and installs the frontend dependencies.

    Run it again whenever you pull: every step is idempotent.
    For a Linux server with systemd and nginx, use deploy/install.sh instead.

.PARAMETER Venv
    Where the virtualenv goes. Defaults to .\.venv next to this script.

.PARAMETER LlmSwitch
    Path or git URL of the llmswitch library, the only source of the LLM provider choice.
    When omitted, a clone sitting next to this repository is picked up automatically.

.PARAMETER SkipFrontend
    Leave frontend\node_modules alone.

.PARAMETER CleanFrontend
    Rebuild node_modules from scratch (npm ci) instead of updating it in place. Stop any running
    dev server first: on Windows a loaded .node binary cannot be deleted.

.PARAMETER SkipWheel
    Do not build the autoskill-local wheel.

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -LlmSwitch C:\Projects\llmswitch
#>
[CmdletBinding()]
param(
    [string]$Venv,
    [string]$LlmSwitch,
    [switch]$SkipFrontend,
    [switch]$CleanFrontend,
    [switch]$SkipWheel
)

$ErrorActionPreference = 'Stop'
# Exit codes are checked one by one below, so a chatty tool writing to stderr is not a failure.
if (Test-Path Variable:PSNativeCommandUseErrorActionPreference) { $PSNativeCommandUseErrorActionPreference = $false }

$Root = $PSScriptRoot
if (-not $Venv) { $Venv = Join-Path $Root '.venv' }
$onWindows = if (Test-Path Variable:IsWindows) { $IsWindows } else { $true }

function Say  { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Note { param([string]$Text) Write-Host "  $Text" }
function Warn { param([string]$Text) Write-Host "  ! $Text" -ForegroundColor Yellow }

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @(),
        [string]$WorkDir,
        [string]$What
    )
    if (-not $What) { $What = $Exe }
    $previous = $null
    if ($WorkDir) { $previous = (Get-Location).Path; Set-Location $WorkDir }
    try {
        # Windows PowerShell turns anything a native command writes to stderr into an error
        # record, and under `Stop` that ends the script. pip and npm talk on stderr all the
        # time; the exit code is what actually says whether they worked.
        $ErrorActionPreference = 'Continue'
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
    } finally {
        if ($previous) { Set-Location $previous }
    }
}

function Test-Native {
    <# Runs a command for its exit code alone, swallowing whatever it says. #>
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments = @())
    $ErrorActionPreference = 'SilentlyContinue'
    & $Exe @Arguments 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Join-Exe {
    param([string]$Dir, [string]$Name)
    $windowsName = Join-Path $Dir "$Name.exe"
    if (Test-Path $windowsName) { return $windowsName }
    return (Join-Path $Dir $Name)
}

# --- Python 3.11+ ------------------------------------------------------------------------

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in '3.13', '3.12', '3.11') {
            $candidates += [pscustomobject]@{ Exe = 'py'; Pre = @("-$version") }
        }
    }
    foreach ($name in 'python3.13', 'python3.12', 'python3.11', 'python3', 'python') {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            $candidates += [pscustomobject]@{ Exe = $name; Pre = @() }
        }
    }
    # The answer is the exit code, not the output: Windows PowerShell 5.1 mangles a `-c` snippet
    # that contains double quotes, and `py` announcing a missing 3.13 on stderr is an answer too.
    foreach ($candidate in $candidates) {
        if (Test-Native $candidate.Exe (@($candidate.Pre) + @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'))) {
            return $candidate
        }
    }
    return $null
}

Say 'Python'
$python = Find-Python
if (-not $python) {
    throw 'No Python 3.11+ found. Install one (python.org, or winget install Python.Python.3.12) and run this again.'
}
$pre = $python.Pre
# One value per line: composing the sentence in Python would need quotes, and 5.1 breaks those.
$found = & $python.Exe @pre -c 'import sys, platform; print(platform.python_version()); print(sys.executable)'
Note ("$($found[0]) at $($found[1])")

# --- virtualenv --------------------------------------------------------------------------

Say "Virtualenv ($Venv)"
function Get-BinDir {
    param([string]$Path)
    $scripts = Join-Path $Path 'Scripts'
    if (Test-Path $scripts) { return $scripts }
    $bin = Join-Path $Path 'bin'
    if (Test-Path $bin) { return $bin }
    return $null
}
$binDir = Get-BinDir $Venv
if (-not $binDir) {
    Invoke-Native -Exe $python.Exe -Arguments (@($python.Pre) + @('-m', 'venv', $Venv)) -What 'python -m venv'
    Note 'created'
    $binDir = Get-BinDir $Venv
} else {
    Note 'already there'
}
if (-not $binDir) { throw "The virtualenv at $Venv has no Scripts or bin directory." }
$py = Join-Exe $binDir 'python'
if (-not (Test-Path $py)) { throw "The virtualenv has no python: remove $Venv and try again." }

Say 'Backend and CLI package'
Invoke-Native -Exe $py -Arguments @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip', 'wheel') -What 'pip upgrade'
# Relative to the repository: `path[extras]` reads more cleanly than a full path with brackets.
Invoke-Native -Exe $py -Arguments @(
    '-m', 'pip', 'install', '--quiet', '-e', 'backend[dev]', '-e', 'packages/autoskill-local[dev]'
) -WorkDir $Root -What 'pip install'
Note 'autoskill + autoskill-local installed in editable mode'

# --- llmswitch: the only source of the LLM provider choice --------------------------------

Say 'Provider library (llmswitch)'
if (-not $LlmSwitch) {
    $sibling = Join-Path (Split-Path -Parent $Root) 'llmswitch'
    if (Test-Path $sibling) {
        $LlmSwitch = (Resolve-Path $sibling).Path
        Note "found next to the repository: $LlmSwitch"
    }
}
if ($LlmSwitch) {
    $pipArgs = if (Test-Path $LlmSwitch) {
        @('-m', 'pip', 'install', '--quiet', '-e', $LlmSwitch)
    } else {
        @('-m', 'pip', 'install', '--quiet', $LlmSwitch)
    }
    Invoke-Native -Exe $py -Arguments $pipArgs -What 'pip install llmswitch'
}
if (Test-Native $py @('-c', 'import llmswitch')) {
    Note ('llmswitch ' + (& $py -c 'import llmswitch; print(llmswitch.__version__)') + ' installed')
} else {
    Warn 'llmswitch is not installed: AutoSkill will start, but no interview, draft or coach'
    Warn 'reply can run until it is. Re-run with -LlmSwitch <path-or-git-url>.'
}

# --- configuration -----------------------------------------------------------------------

Say 'Configuration (backend\.env)'
$envFile = Join-Path $Root 'backend\.env'
if (Test-Path $envFile) {
    Note 'kept as it is'
} else {
    $secret = & $py -c 'import secrets; print(secrets.token_urlsafe(48))'
    $lines = Get-Content (Join-Path $Root '.env.example') | ForEach-Object {
        if ($_ -match '^AUTOSKILL_SECRET_KEY=') { "AUTOSKILL_SECRET_KEY=$secret" } else { $_ }
    }
    # No BOM: the first setting of a .env file must not start with three invisible bytes.
    [System.IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
    Note 'written from .env.example, with a secret key of its own'
}

Say 'Database schema'
Invoke-Native -Exe (Join-Exe $binDir 'alembic') -Arguments @('upgrade', 'head') `
    -WorkDir (Join-Path $Root 'backend') -What 'alembic upgrade head'

if (-not $SkipWheel) {
    Say 'autoskill-local wheel (served at /dl/autoskill-local/latest)'
    Invoke-Native -Exe $py -Arguments @(
        '-m', 'pip', 'wheel', '--quiet', '--no-deps',
        '-w', (Join-Path $Root 'backend\data\dist'),
        (Join-Path $Root 'packages\autoskill-local')
    ) -What 'pip wheel'
    Note 'built'
}

# --- frontend ----------------------------------------------------------------------------

if (-not $SkipFrontend) {
    Say 'Frontend'
    $npm = 'npm'
    if ($onWindows -and (Get-Command 'npm.cmd' -ErrorAction SilentlyContinue)) { $npm = 'npm.cmd' }
    if (-not (Get-Command $npm -ErrorAction SilentlyContinue)) {
        throw 'npm not found. Install Node 20+ (winget install OpenJS.NodeJS.LTS) and run this again.'
    }
    if (Get-Command node -ErrorAction SilentlyContinue) {
        # `-p process.versions.node` carries no quotes, so 5.1 hands it over intact; the split
        # happens here instead.
        $nodeMajor = [int]((& node -p process.versions.node) -split '\.')[0]
        if ($nodeMajor -lt 20) { Warn "Node $nodeMajor is older than the 20 this project expects." }
    }

    # `npm ci` deletes node_modules before installing, and on Windows a .node binary a running
    # dev server has loaded cannot be unlinked - the run dies halfway, leaving a half-deleted
    # tree. A tree that is already there is updated in place instead; -CleanFrontend forces the
    # reproducible route, and refuses to start it while something is holding the files.
    $frontend = Join-Path $Root 'frontend'
    $modules = Join-Path $frontend 'node_modules'
    $command = if ($CleanFrontend -or -not (Test-Path $modules)) { 'ci' } else { 'install' }
    if ($command -eq 'ci' -and (Test-Path $modules) -and $onWindows) {
        $holders = Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='esbuild.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*$frontend*" -or $_.ExecutablePath -like "$frontend*" }
        if ($holders) {
            throw ("node_modules is in use by pid " + ($holders.ProcessId -join ', ') +
                   ' - stop the dev server (start.ps1, or npm run dev) and run this again.')
        }
    }
    try {
        Invoke-Native -Exe $npm -Arguments @($command, '--no-audit', '--no-fund') `
            -WorkDir $frontend -What "npm $command"
    } catch {
        Warn 'npm could not write into node_modules.'
        Warn 'A dev server holding those files is the usual reason: stop start.ps1 / npm run dev,'
        Warn 'then run this again. Antivirus and an open editor can hold them too.'
        throw
    }
    Note "dependencies installed (npm $command)"
}

Say 'Done'
Write-Host @'
  Start everything with .\start.ps1  (API on :8000, UI on :5173)

  The first account you register in the UI becomes the administrator. Then open
  Administration -> AI providers and configure the model: that panel is the only
  place the choice of provider comes from.
'@
