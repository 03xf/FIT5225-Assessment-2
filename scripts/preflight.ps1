<#!
.SYNOPSIS
Runs non-destructive release checks before the FIT5225 demo or submission.

.DESCRIPTION
This script never deploys or changes cloud resources. It verifies local tests,
Terraform syntax, Git state and the presence of external deployment tools.
Use -RunModelSmoke only after Worker ML dependencies are installed.
#>
param([switch]$RunModelSmoke)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$terraformRoot = Join-Path $projectRoot "infra\terraform"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Local Python environment is missing: $python"
}

Push-Location $projectRoot
try {
  Write-Host "[1/5] Python tests"
  & $python -m pytest -q
  if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }

  Write-Host "[2/5] Terraform validation"
  Push-Location $terraformRoot
  try {
    terraform fmt -check
    if ($LASTEXITCODE -ne 0) { throw "Terraform formatting check failed" }
    terraform validate
    if ($LASTEXITCODE -ne 0) { throw "Terraform validation failed" }
  } finally { Pop-Location }

  Write-Host "[3/5] Git evidence"
  git status --short
  git log --oneline -10

  Write-Host "[4/5] Deployment tool availability"
  foreach ($tool in @("aws", "gcloud", "docker")) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue
    if ($command) { Write-Host "FOUND: $tool -> $($command.Source)" }
    else { Write-Warning "MISSING: $tool (required only for real cloud deployment)" }
  }
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker version --format '{{.Server.Version}}' 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Docker CLI is installed but the Docker daemon is not ready." }
  }

  if ($RunModelSmoke) {
    Write-Host "[5/5] Real supplied-model smoke test"
    & $python "scripts\run_model_smoke.py"
    if ($LASTEXITCODE -ne 0) { throw "Model smoke test failed" }
  } else {
    Write-Host "[5/5] Model smoke test skipped; rerun with -RunModelSmoke after installing worker dependencies."
  }
} finally {
  Pop-Location
}
