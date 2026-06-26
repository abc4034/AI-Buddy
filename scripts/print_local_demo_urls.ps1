param(
  [string]$HostIp = ""
)

$ErrorActionPreference = "Stop"

function Test-PrivateIPv4 {
  param([string]$IpAddress)

  $parsedIp = $null
  if (-not [System.Net.IPAddress]::TryParse($IpAddress, [ref]$parsedIp)) {
    return $false
  }

  if ($parsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    return $false
  }

  $octets = $IpAddress.Split(".")
  $first = [int]$octets[0]
  $second = [int]$octets[1]

  if ($first -eq 10) {
    return $true
  }

  if (($first -eq 192) -and ($second -eq 168)) {
    return $true
  }

  if (($first -eq 172) -and ($second -ge 16) -and ($second -le 31)) {
    return $true
  }

  return $false
}

function Select-PreferredLanIp {
  param(
    [Parameter(ValueFromPipeline = $true)]
    [object]$InputObject
  )

  begin {
    $candidates = @()
  }

  process {
    if ($null -eq $InputObject) {
      return
    }

    if ($InputObject -is [string]) {
      $ipAddress = $InputObject
    }
    else {
      $ipAddress = $InputObject.IPAddress
    }

    if (-not [string]::IsNullOrWhiteSpace($ipAddress) -and (Test-PrivateIPv4 -IpAddress $ipAddress)) {
      $candidates += $ipAddress
    }
  }

  end {
    $preferred = $candidates |
      Where-Object { $_ -eq "192.168.2.9" } |
      Select-Object -First 1

    if (-not $preferred) {
      throw "Could not auto-detect demo host IP 192.168.2.9 from private LAN candidates. Pass -HostIp explicitly."
    }

    return $preferred
  }
}

function Get-DefaultLanIp {
  return Get-NetIPAddress -AddressFamily IPv4 | Select-PreferredLanIp
}

function Assert-DemoHostIp {
  param([string]$IpAddress)

  if ($IpAddress -ne "192.168.2.9") {
    throw "HostIp must be the Task 2 demo host IP 192.168.2.9 so device-facing URLs match the first-demo contract."
  }

  return $IpAddress
}

function Invoke-PrintLocalDemoUrls {
  param([string]$HostIp)

  if ([string]::IsNullOrWhiteSpace($HostIp)) {
    $HostIp = Get-DefaultLanIp
  }
  else {
    $HostIp = Assert-DemoHostIp -IpAddress $HostIp
  }

  Write-Host "Buddy Brain health: http://${HostIp}:8010/health"
  Write-Host "Buddy Brain OpenAI base_url: http://${HostIp}:8010/v1"
  Write-Host "XiaoZhi OTA URL: http://${HostIp}:8003/xiaozhi/ota/"
  Write-Host "XiaoZhi WebSocket URL: ws://${HostIp}:8000/xiaozhi/v1/"
  Write-Host "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://${HostIp}:8003/xiaozhi/ota/"
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-PrintLocalDemoUrls -HostIp $HostIp
}
