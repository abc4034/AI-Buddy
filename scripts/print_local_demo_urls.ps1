param(
  [string]$HostIp = ""
)

$ErrorActionPreference = "Stop"

function Get-DefaultLanIp {
  $preferred = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.IPAddress -notlike "192.168.182.*" -and
      $_.IPAddress -notlike "192.168.254.*"
    } |
    Sort-Object -Property InterfaceMetric |
    Select-Object -First 1

  if (-not $preferred) {
    throw "Could not auto-detect a LAN IPv4 address. Pass -HostIp manually."
  }

  return $preferred.IPAddress
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $HostIp = Get-DefaultLanIp
}

Write-Host "Buddy Brain health: http://$HostIp:8010/health"
Write-Host "Buddy Brain OpenAI base_url: http://$HostIp:8010/v1"
Write-Host "XiaoZhi OTA URL: http://$HostIp:8003/xiaozhi/ota/"
Write-Host "XiaoZhi WebSocket URL: ws://$HostIp:8000/xiaozhi/v1/"
Write-Host "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://$HostIp:8003/xiaozhi/ota/"
