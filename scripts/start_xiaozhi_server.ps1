param(
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server",
  [string]$CondaEnv = "xiaozhi-esp32-server"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $ServerDir "app.py"))) {
  throw "XiaoZhi server app.py not found. Run .\scripts\setup_xiaozhi_server.ps1 first."
}

if (-not (Test-Path (Join-Path $ServerDir "data\.config.yaml"))) {
  throw "XiaoZhi data\.config.yaml not found. Run .\scripts\render_xiaozhi_config.ps1 first."
}

Write-Host "Starting XiaoZhi server from $ServerDir with conda env $CondaEnv"
Push-Location $ServerDir
try {
  & conda run -n $CondaEnv python app.py
}
finally {
  Pop-Location
}
