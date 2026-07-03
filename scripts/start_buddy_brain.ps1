param(
  [int]$Port = 8010,
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Assert-BuddyCorePort {
  param([int]$Port)

  if ($Port -ne 8010) {
    throw "Buddy Core demo contract requires -Port 8010. Received $Port."
  }

  return $Port
}

function Test-BuddyCoreHealthy {
  param([int]$Port)

  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    return $health.status -eq "ok"
  }
  catch {
    return $false
  }
}

function Invoke-StartBuddyCore {
  param(
    [int]$Port,
    [string]$CondaEnv = "xiaozhi-env"
  )

  $Port = Assert-BuddyCorePort -Port $Port

  if (Test-BuddyCoreHealthy -Port $Port) {
    Write-Host "Buddy Core already running on http://127.0.0.1:$Port"
    return
  }

  $repoRoot = Get-RepoRoot
  $envFile = Join-Path $repoRoot ".env"

  if (-not (Test-Path $envFile)) {
    Write-Warning ".env was not found. Buddy Core may fail if OPENAI_API_KEY is not set in the environment."
  }

  Write-Host "Starting Buddy Core on 0.0.0.0:$Port with conda env $CondaEnv"
  Push-Location $repoRoot
  try {
    & conda run --no-capture-output -n $CondaEnv python -m uvicorn buddy_brain.app:app --host 0.0.0.0 --port $Port
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartBuddyCore -Port $Port -CondaEnv $CondaEnv
}
