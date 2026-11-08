param()
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$state = Join-Path $root '.public-demo'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$python = Join-Path $root '.venv\Scripts\python.exe'
$cloudflared = (Get-Command cloudflared -ErrorAction Stop).Source
function Start-Detached([string]$name, [string]$command) {
    $directory = $root.Replace("'", "''")
    $log = (Join-Path $state "$name.log").Replace("'", "''")
    $runner = "Set-Location -LiteralPath '$directory'; `$ErrorActionPreference='Continue'; Get-ChildItem Env: | Where-Object { `$_.Name -match '^(N8N|SLACK)_' } | ForEach-Object { Remove-Item ('Env:' + `$_.Name) }; & { $command } *> '$log'"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runner))
    $process = Start-Process powershell.exe -ArgumentList @('-NoProfile','-EncodedCommand',$encoded) -WorkingDirectory $root -WindowStyle Hidden -PassThru
    Set-Content (Join-Path $state "$name.pid") $process.Id
}
$mutex = New-Object Threading.Mutex($false, 'Local\RealocaAIPublicDemo')
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (!$locked) { throw 'Public demo startup already running.' }
    if (!(Test-Path (Join-Path $state 'snapshot.db'))) {
        & $python (Join-Path $PSScriptRoot 'prepare_public_demo.py')
        if ($LASTEXITCODE -ne 0) { throw 'Snapshot failed.' }
    }
    $healthy = $false
    try {
        $response = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health -TimeoutSec 3
        $healthy = $response.Headers['X-Realoca-Mode'] -eq 'public-read-only'
        if (!$healthy) { throw 'Port 8002 occupied by another service.' }
    } catch [System.Net.WebException] { }
    if (!$healthy) {
        Start-Detached 'api' "& '$($python.Replace("'", "''"))' -m uvicorn app.public_demo:app --host 127.0.0.1 --port 8002 --no-server-header"
        $ready = $false
        for ($i=0; $i -lt 30; $i++) {
            try { $response = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health -TimeoutSec 2; $ready = $response.Headers['X-Realoca-Mode'] -eq 'public-read-only'; if ($ready) { break } } catch { }
            Start-Sleep -Milliseconds 500
        }
        if (!$ready) { throw "Public API failed. See $state\api.log" }
    }
    # Reuse only the tunnel associated with our saved child process.
    $pidFile = Join-Path $state 'tunnel.pid'
    $tunnelAlive = $false
    if (Test-Path $pidFile) {
        $savedId = [int](Get-Content $pidFile)
        $owner = Get-Process -Id $savedId -ErrorAction SilentlyContinue
        $tunnelAlive = $null -ne $owner -and $owner.ProcessName -eq 'powershell'
    }
    if (!$tunnelAlive) {
        Start-Detached 'tunnel' "& '$($cloudflared.Replace("'", "''"))' tunnel --no-autoupdate --url http://127.0.0.1:8002 --protocol http2"
    }
    $url = $null
    for ($i=0; $i -lt 60; $i++) {
        $log = Join-Path $state 'tunnel.log'
        if (Test-Path $log) {
            $match = [regex]::Match([string](Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($match.Success) { $url = $match.Value; break }
        }
        Start-Sleep -Milliseconds 500
    }
    if (!$url) { throw "Tunnel URL unavailable. See $state\tunnel.log" }
    $reachable = $false
    for ($i=0; $i -lt 6; $i++) {
        try {
            $remote = Invoke-WebRequest -UseBasicParsing "$url/health" -TimeoutSec 5
            $reachable = $remote.StatusCode -eq 200 -and $remote.Headers['X-Realoca-Mode'] -eq 'public-read-only'
            if ($reachable) { break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (!$reachable) { throw "Tunnel did not pass HTTPS health verification: $url. Inspect tunnel.log before restarting only the public services." }
    Set-Content (Join-Path $state 'url.txt') $url
    Write-Host "Public read-only demo: $url"
    Write-Host 'Keep this computer and internet active. Restarting the tunnel changes its URL.'
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
