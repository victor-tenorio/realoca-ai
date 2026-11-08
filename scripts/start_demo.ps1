param()
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$logs = Join-Path $root '.demo-logs'
$python = Join-Path $root '.venv\Scripts\python.exe'
$node = (Get-Command node -ErrorAction Stop).Source
$vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
foreach ($required in @($python, $vite, (Join-Path $root 'realoca.db'))) {
    if (!(Test-Path -LiteralPath $required)) { throw "Arquivo necessario ausente: $required" }
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null
function Test-Port([int]$port) {
    foreach ($address in @('127.0.0.1', '::1')) {
        $client = New-Object Net.Sockets.TcpClient ([Net.IPAddress]::Parse($address).AddressFamily)
        try { $client.Connect($address, $port); return $true }
        catch { }
        finally { $client.Dispose() }
    }
    return $false
}
function Assert-Http([string]$url, [string]$pattern) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch $pattern) {
        throw "Resposta inesperada em $url. Nenhum processo existente sera encerrado."
    }
}
function Start-ServiceProcess([string]$name, [string]$command, [int]$port) {
    $escapedRoot = $root.Replace("'", "''")
    $log = (Join-Path $logs "$name.log").Replace("'", "''")
    $runner = "Set-Location -LiteralPath '$escapedRoot'; Start-Transcript -Path '$log' -Append; $command; Stop-Transcript"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($runner))
    $process = Start-Process powershell.exe -ArgumentList @('-NoProfile', '-NoExit', '-EncodedCommand', $encoded) -WorkingDirectory $root -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $logs "$name.pid") -Value $process.Id
    $deadline = (Get-Date).AddSeconds(30)
    while (!(Test-Port $port)) {
        if ($process.HasExited -or (Get-Date) -gt $deadline) { throw "Falha ao iniciar $name. Consulte $log" }
        Start-Sleep -Milliseconds 300
    }
    Write-Host "$name iniciado na porta $port. Log: $log"
}
$mutex = New-Object Threading.Mutex($false, 'Local\RealocaAIStartDemo')
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (!$locked) { throw 'Outra inicializacao da demo esta em andamento.' }
    if (!(Test-Port 8001)) {
        $db = (Join-Path $root 'realoca.db').Replace('\', '/').Replace("'", "''")
        $exe = $python.Replace("'", "''")
        Start-ServiceProcess 'backend' "`$env:DATABASE_URL='sqlite:///$db'; `$env:DEMO_REFERENCE_DATE='2026-11-08'; & '$exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8001" 8001
    }
    Assert-Http 'http://127.0.0.1:8001/health' 'ok'
    if (!(Test-Port 5173)) {
        $exe = $node.Replace("'", "''")
        $entry = $vite.Replace("'", "''")
        Start-ServiceProcess 'frontend' "Set-Location -LiteralPath 'frontend'; `$env:VITE_DEV_PROXY_TARGET='http://127.0.0.1:8001'; & '$exe' '$entry' --host localhost --port 5173 --strictPort" 5173
    }
    Assert-Http 'http://localhost:5173' 'Realoca'
    Assert-Http 'http://localhost:5173/api/v1/dashboard' 'planned_hours'
    Write-Host 'Demo pronta: http://localhost:5173 (API: http://127.0.0.1:8001)'
    Write-Host "Logs persistentes em $logs. O banco existente foi preservado."
}
finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
