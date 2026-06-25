param(
  [string]$HostIp = ""
)

$ErrorActionPreference = "Stop"

function Convert-IPv4ToUInt32 {
  param([string]$IpAddress)

  $bytes = [System.Net.IPAddress]::Parse($IpAddress).GetAddressBytes()
  [Array]::Reverse($bytes)
  return [System.BitConverter]::ToUInt32($bytes, 0)
}

function Get-DefaultLanIp {
  $privateIps = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -like "10.*" -or
      $_.IPAddress -like "172.16.*" -or
      $_.IPAddress -like "172.17.*" -or
      $_.IPAddress -like "172.18.*" -or
      $_.IPAddress -like "172.19.*" -or
      $_.IPAddress -like "172.2*" -or
      $_.IPAddress -like "172.30.*" -or
      $_.IPAddress -like "172.31.*" -or
      $_.IPAddress -like "192.168.*"
    } |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*"
    } |
    Select-Object -ExpandProperty IPAddress

  $preferred = $privateIps | Where-Object { $_ -like "192.168.2.*" } | Sort-Object | Select-Object -First 1

  if (-not $preferred) {
    $preferred = $privateIps |
      Sort-Object { Convert-IPv4ToUInt32 $_ } |
      Select-Object -First 1
  }

  if (-not $preferred) {
    throw "Could not auto-detect a LAN IPv4 address. Pass -HostIp manually."
  }

  return $preferred
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $HostIp = Get-DefaultLanIp
}

Write-Host "Buddy Brain health: http://$HostIp:8010/health"
Write-Host "Buddy Brain OpenAI base_url: http://$HostIp:8010/v1"
Write-Host "XiaoZhi OTA URL: http://$HostIp:8003/xiaozhi/ota/"
Write-Host "XiaoZhi WebSocket URL: ws://$HostIp:8000/xiaozhi/v1/"
Write-Host "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://$HostIp:8003/xiaozhi/ota/"
