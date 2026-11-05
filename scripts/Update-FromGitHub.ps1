[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$GitPath = 'C:\Program Files\Git\cmd\git.exe',
    [string]$DockerPath = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$ProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$stateDirectory = Join-Path $ProjectPath 'tmp\auto-deploy'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$logPath = Join-Path $stateDirectory ('deploy-{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))
$stampPath = Join-Path $stateDirectory 'deployed-commit.txt'
$lockHandle = $null

function Write-DeployLog([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Invoke-DeployCommand([string]$Executable, [string[]]$CommandArguments) {
    # Windows PowerShell treats native stderr as ErrorRecords, even on success.
    $ErrorActionPreference = 'Continue'
    $lines = @(& $Executable @CommandArguments 2>&1 | ForEach-Object { "$_" })
    $commandExitCode = $LASTEXITCODE
    if ($commandExitCode -ne 0) {
        throw ('{0} failed ({1}): {2}' -f (Split-Path -Leaf $Executable), $commandExitCode, ($lines -join "`n"))
    }
    return ($lines -join "`n")
}

try {
    try {
        $lockHandle = [System.IO.File]::Open((Join-Path $stateDirectory 'deploy.lock'),
            [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
        Write-Output 'Another deployment check is already running. Skipping.'
        exit 0
    }
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'Never'
    $env:GCM_GUI_PROMPT = '0'
    Set-Location -LiteralPath $ProjectPath
    $branch = Invoke-DeployCommand $GitPath @('branch', '--show-current')
    if ($branch.Trim() -ne 'main') {
        throw 'Deployment requires the main branch; the current branch was left unchanged.'
    }
    $dirty = Invoke-DeployCommand $GitPath @('status', '--porcelain')
    if ($dirty.Trim()) {
        Write-DeployLog 'Skipped: uncommitted or untracked source files. Commit or stash them before updating.'
        exit 0
    }
    $null = Invoke-DeployCommand $GitPath @('fetch', '--prune', 'origin', 'main')
    $localCommit = (Invoke-DeployCommand $GitPath @('rev-parse', 'HEAD')).Trim()
    $remoteCommit = (Invoke-DeployCommand $GitPath @('rev-parse', 'refs/remotes/origin/main')).Trim()
    $deployedCommit = if (Test-Path -LiteralPath $stampPath) { (Get-Content -LiteralPath $stampPath -Raw).Trim() } else { '' }
    if ($localCommit -eq $remoteCommit -and $deployedCommit -eq $localCommit) {
        Write-DeployLog "No update needed: $($localCommit.Substring(0, 7))."
        exit 0
    }
    # Refuse divergent history instead of resetting or discarding local commits.
    $null = Invoke-DeployCommand $GitPath @('merge-base', '--is-ancestor', 'HEAD', 'refs/remotes/origin/main')
    if ($CheckOnly) {
        Write-DeployLog "Update pending: $($remoteCommit.Substring(0, 7)). Check-only; no source or container changes."
        exit 0
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectPath '.env'))) {
        throw 'The local .env file is missing. Deployment was not attempted.'
    }
    $null = Invoke-DeployCommand $DockerPath @('info', '--format', '{{.ServerVersion}}')
    if ($localCommit -ne $remoteCommit) {
        Write-DeployLog "Updating main to $($remoteCommit.Substring(0, 7))."
        Write-DeployLog (Invoke-DeployCommand $GitPath @('merge', '--ff-only', 'refs/remotes/origin/main'))
    }
    # Build first: a failed build leaves the currently running container in place.
    Write-DeployLog 'Building the app image.'
    Write-DeployLog (Invoke-DeployCommand $DockerPath @('compose', 'build', 'app'))
    Write-DeployLog 'Replacing the app container and waiting for its health check.'
    Write-DeployLog (Invoke-DeployCommand $DockerPath @('compose', 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'app'))
    # Only mark successful deployments. A failed build/start is retried next morning.
    Set-Content -LiteralPath $stampPath -Value $remoteCommit -Encoding ASCII
    Write-DeployLog "Deployment succeeded: $($remoteCommit.Substring(0, 7))."
    exit 0
} catch {
    Write-DeployLog "FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    if ($null -ne $lockHandle) { $lockHandle.Dispose() }
}
