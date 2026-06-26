param(
  [int]$Port = 8010
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Assert-BuddyBrainPort {
  param([int]$Port)

  if ($Port -ne 8010) {
    throw "Buddy Brain demo contract requires -Port 8010. Received $Port."
  }

  return $Port
}

function Invoke-StartBuddyBrain {
  param([int]$Port)

  $Port = Assert-BuddyBrainPort -Port $Port
  $repoRoot = Get-RepoRoot
  $envFile = Join-Path $repoRoot ".env"

  if (-not (Test-Path $envFile)) {
    Write-Warning ".env was not found. Buddy Brain may fail if OPENAI_API_KEY is not set in the environment."
  }

  Write-Host "Starting Buddy Brain on 0.0.0.0:$Port"
  Push-Location $repoRoot
  try {
    & py -3.10 -m uvicorn buddy_brain.app:app --host 0.0.0.0 --port $Port
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartBuddyBrain -Port $Port
}
