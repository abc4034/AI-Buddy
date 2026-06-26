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
      Where-Object { $_ -like "192.168.2.*" } |
      Sort-Object { Convert-IPv4ToUInt32 $_ } |
      Select-Object -First 1

    if (-not $preferred) {
      $preferred = $candidates |
        Sort-Object { Convert-IPv4ToUInt32 $_ } |
        Select-Object -First 1
    }

    if (-not $preferred) {
      throw "Could not auto-detect a LAN IPv4 address. Pass -HostIp manually."
    }

    return $preferred
  }
}

function Get-DefaultLanIp {
  return Get-NetIPAddress -AddressFamily IPv4 | Select-PreferredLanIp
}

function Assert-PrivateLanIp {
  param([string]$IpAddress)

  if (-not (Test-PrivateIPv4 -IpAddress $IpAddress)) {
    throw "HostIp must be a private LAN IPv4 address so device-facing URLs use your local network."
  }

  return $IpAddress
}

function Invoke-PrintLocalDemoUrls {
  param([string]$HostIp)

  if ([string]::IsNullOrWhiteSpace($HostIp)) {
    $HostIp = Get-DefaultLanIp
  }
  else {
    $HostIp = Assert-PrivateLanIp -IpAddress $HostIp
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
