param(
  [int]$Port = 8010
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
  Write-Warning ".env was not found. Buddy Brain may fail if OPENAI_API_KEY is not set in the environment."
}

Write-Host "Starting Buddy Brain on 0.0.0.0:$Port"
& py -3.10 -m uvicorn buddy_brain.app:app --host 0.0.0.0 --port $Port
