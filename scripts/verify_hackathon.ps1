# Testes e planejamento do caso real, sem repetir tentativas existentes.
# Exemplo: .\scripts\verify_hackathon.ps1 -Plan
param(
    [switch]$Plan,
    [string]$CaseId = "case-9a9b8667-86ae-447a-be45-d571614144e8",
    [string]$Api = "http://127.0.0.1:8001"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Ambiente Python nao encontrado em $python" }

Write-Host "1/3: Testes integrados..."
$testFiles = @(
    "tests/integration/test_slack_only_planning.py",
    "tests/integration/test_planning_bridge.py",
    "tests/integration/test_attempt_event_endpoint.py",
    "tests/integration/test_event_processing.py"
)
& $python -m pytest @testFiles -q
if ($LASTEXITCODE -ne 0) { throw "TESTES FALHARAM. Nenhum planejamento executado." }

Write-Host "2/3: Consultando caso..."
$caseUri = "$Api/api/v1/cases/$CaseId"
$details = Invoke-RestMethod -Method Get -Uri $caseUri
$proposals = @($details.proposals | Where-Object { $null -ne $_ })
Write-Host "Caso: $($details.case_id) | status: $($details.status) | propostas: $($proposals.Count)"

if ($Plan -and $proposals.Count -eq 0) {
    Write-Host "3/3: Planejando UMA vez. Isto pode gerar convites no Slack."
    $planned = Invoke-RestMethod -Method Post -Uri "$caseUri/plan"
    $planned | ConvertTo-Json -Depth 10
} elseif ($Plan) {
    Write-Host "Planejamento pulado: ja existem propostas. Nao duplicar."
} else {
    Write-Host "3/3: Modo somente leitura. Use -Plan para gerar um plano real."
}
Write-Host "Estado do caso:"
Invoke-RestMethod -Method Get -Uri $caseUri | ConvertTo-Json -Depth 10
Write-Host "Auditoria:"
Invoke-RestMethod -Method Get -Uri "$Api/api/v1/audit?case_id=$CaseId" | ConvertTo-Json -Depth 8
