param(
  [string]$Destination = ".run\xiaozhi-esp32-server",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$zipUrl = "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/heads/main.zip"
$runDir = Split-Path -Parent $Destination
$zipPath = Join-Path $runDir "xiaozhi-esp32-server-main.zip"
$extractDir = Join-Path $runDir "xiaozhi-esp32-server-main"

if ((Test-Path $Destination) -and -not $Force) {
  Write-Host "XiaoZhi server already exists at $Destination"
  exit 0
}

if (Test-Path $Destination) {
  Remove-Item -Recurse -Force -LiteralPath $Destination
}
if (Test-Path $extractDir) {
  Remove-Item -Recurse -Force -LiteralPath $extractDir
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Write-Host "Downloading $zipUrl"
Invoke-WebRequest -UseBasicParsing $zipUrl -OutFile $zipPath

Write-Host "Extracting XiaoZhi server"
Expand-Archive -Force -LiteralPath $zipPath -DestinationPath $runDir
Move-Item -LiteralPath $extractDir -Destination $Destination

$serverDir = Join-Path $Destination "main\xiaozhi-server"
$dataDir = Join-Path $serverDir "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

Write-Host "Prepared XiaoZhi server at $serverDir"
Write-Host "Next: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1"
