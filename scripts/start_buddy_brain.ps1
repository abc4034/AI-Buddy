param(
  [int]$Port = 8010
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
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
