# Rotate cinderhaven_dagster and cinderhaven_ci_reader and place both passwords.
# The owner runs this, from the platform repo folder, with:
#
#   powershell -ExecutionPolicy Bypass -File scripts\rotate_and_place.ps1
#
# It opens a Fly proxy to production on port 15432, runs scripts\rotate_and_place.py
# (which shows what it will do and asks for APPLY), and always closes the proxy.
# No password is printed. See rotate_and_place.py for the steps.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$port = 15432

foreach ($tool in 'flyctl', 'gh', 'python', 'docker') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "Missing $tool on PATH. Nothing changed." -ForegroundColor Red
        exit 1
    }
}

# The backup runs pg_dump in a container, so Docker must be up. Docker Desktop on
# this machine crash-loops on stale socket files; the recorded fix is to rename
# the two socket folders aside and start it once (never a factory reset).
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running; starting Docker Desktop (up to 3 minutes) ..."
    Get-Process *docker* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    foreach ($p in "$env:LOCALAPPDATA\Docker\run", "$env:LOCALAPPDATA\docker-secrets-engine") {
        if (Test-Path $p) { Rename-Item $p ((Split-Path $p -Leaf) + ".stale-$stamp") }
    }
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 3
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "Docker did not start. Nothing changed." -ForegroundColor Red; exit 1 }
}

Write-Host "Opening the Fly proxy to cinderhaven-db on port $port ..."
$proxy = Start-Process flyctl -ArgumentList "proxy $($port):5432 -a cinderhaven-db" -PassThru -WindowStyle Hidden
$code = 1
try {
    $open = $false
    for ($i = 0; $i -lt 30 -and -not $open; $i++) {
        Start-Sleep -Seconds 1
        try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $port); $c.Close(); $open = $true } catch { }
    }
    if (-not $open) { throw "The Fly proxy did not open on port $port. Is flyctl logged in (flyctl auth whoami)?" }

    # Production through a fly tunnel: the guard refuses it unless this is set, for this run only.
    $env:ALLOW_PROD_DB = '1'
    $env:ROTATE_PROXY_PORT = "$port"
    python scripts\rotate_and_place.py
    $code = $LASTEXITCODE
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}
finally {
    Remove-Item Env:ALLOW_PROD_DB -ErrorAction SilentlyContinue
    Remove-Item Env:ROTATE_PROXY_PORT -ErrorAction SilentlyContinue
    if ($proxy -and -not $proxy.HasExited) { Stop-Process -Id $proxy.Id -Force }
    Write-Host "Fly proxy closed."
}
exit $code
