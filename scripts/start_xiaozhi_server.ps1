param(
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server",
  [string]$CondaEnv = "xiaozhi-esp32-server"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

if ([System.IO.Path]::IsPathRooted($ServerDir)) {
  $resolvedServerDir = [System.IO.Path]::GetFullPath($ServerDir)
}
else {
  $resolvedServerDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDir))
}

if (-not (Test-Path (Join-Path $resolvedServerDir "app.py"))) {
  throw "XiaoZhi server app.py not found. Run .\scripts\setup_xiaozhi_server.ps1 first."
}

if (-not (Test-Path (Join-Path $resolvedServerDir "data\.config.yaml"))) {
  throw "XiaoZhi data\.config.yaml not found. Run .\scripts\render_xiaozhi_config.ps1 first."
}

Write-Host "Starting XiaoZhi server from $resolvedServerDir with conda env $CondaEnv"
Push-Location $resolvedServerDir
try {
  & conda run -n $CondaEnv python app.py
}
finally {
  Pop-Location
}
