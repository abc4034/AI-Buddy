param(
  [string]$DeviceA = "debug-device-a",
  [string]$DeviceB = "debug-device-b",
  [string]$Url = "http://127.0.0.1:8010/v1/chat/completions",
  [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $PSCommandPath
$smokeChat = Join-Path $scriptDir "smoke_chat.ps1"

Write-Host "Compare devices from /memory?device_id=..."

Write-Host "Smoke device A: $DeviceA"
& $smokeChat -DeviceId $DeviceA -ClientId $DeviceA -SessionId "$DeviceA-session" -Url $Url
$deviceAMemoryUrl = "${MemoryBaseUrl}?device_id=$([uri]::EscapeDataString($DeviceA))"
Write-Host ""
Write-Host "Memory URL A: $deviceAMemoryUrl"
Write-Host ""

Write-Host "Smoke device B: $DeviceB"
& $smokeChat -DeviceId $DeviceB -ClientId $DeviceB -SessionId "$DeviceB-session" -Url $Url
$deviceBMemoryUrl = "${MemoryBaseUrl}?device_id=$([uri]::EscapeDataString($DeviceB))"
Write-Host ""
Write-Host "Memory URL B: $deviceBMemoryUrl"
