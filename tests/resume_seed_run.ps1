# Start (or resume) U18's 30-seed harness run after a shutdown, in one line:
#
#   powershell -ExecutionPolicy Bypass -File tests/resume_seed_run.ps1
#
# 1. Starts Docker Desktop if its engine is not answering, and waits for it.
# 2. Starts the harness database (always compose project "cinderhaven-data-platform",
#    so a worktree reuses the same container and volume, never a second one on 55432).
# 3. Waits until Postgres accepts connections.
# 4. Runs tests/seed_runs.py --seeds 30, which skips every seed already saved in
#    output/seed_runs/progress-<commit>-30seeds.jsonl and judges from the saved results.
# Exits with the run's own exit code (0 = every gate passed).
# "Continue", not "Stop": in Windows PowerShell 5.1 a native command's stderr
# (docker info while the engine is down; docker compose's progress lines) is a
# terminating error under "Stop". Every step checks its own $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Test-DockerEngine {
    docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-DockerEngine)) {
    Write-Host "Starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-DockerEngine)) {
        if ((Get-Date) -gt $deadline) { throw "Docker engine did not answer within 180 s" }
        Start-Sleep -Seconds 5
    }
}
Write-Host "Docker engine up."

docker compose -p cinderhaven-data-platform --env-file tests/harness.env up -d harness-db
if ($LASTEXITCODE -ne 0) { throw "docker compose up harness-db failed (exit $LASTEXITCODE)" }

$deadline = (Get-Date).AddSeconds(90)
while ($true) {
    docker compose -p cinderhaven-data-platform --env-file tests/harness.env exec -T harness-db pg_isready -q *> $null
    if ($LASTEXITCODE -eq 0) { break }
    if ((Get-Date) -gt $deadline) { throw "harness database not ready within 90 s" }
    Start-Sleep -Seconds 3
}
Write-Host "Harness database ready. Running (or resuming) the 30-seed run..."

python tests/seed_runs.py --seeds 30
exit $LASTEXITCODE
