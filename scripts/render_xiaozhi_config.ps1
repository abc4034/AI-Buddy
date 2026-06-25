param(
  [string]$HostIp = "",
  [string]$Output = ""
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

$argsList = @(
  "-3.10",
  "-m",
  "integrations.xiaozhi_server.render_config",
  "--host-ip",
  $HostIp,
  "--repo-root",
  (Get-Location).Path
)

if (-not [string]::IsNullOrWhiteSpace($Output)) {
  $argsList += @("--output", $Output)
}

Write-Host "Rendering XiaoZhi config for host IP $HostIp"
& py @argsList
