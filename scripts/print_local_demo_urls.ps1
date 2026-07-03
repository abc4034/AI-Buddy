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

function Test-VirtualLanInterface {
  param([string]$InterfaceAlias)

  if ([string]::IsNullOrWhiteSpace($InterfaceAlias)) {
    return $false
  }

  return $InterfaceAlias -match "VMware|VirtualBox|vEthernet|Docker|Loopback|Hyper-V|WSL|Npcap"
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
      $interfaceAlias = ""
    }
    else {
      $ipAddress = $InputObject.IPAddress
      $interfaceAlias = $InputObject.InterfaceAlias
    }

    if (-not [string]::IsNullOrWhiteSpace($ipAddress) -and (Test-PrivateIPv4 -IpAddress $ipAddress)) {
      $candidates += [pscustomobject]@{
        IPAddress = $ipAddress
        InterfaceAlias = $interfaceAlias
      }
    }
  }

  end {
    $preferred = $candidates |
      Where-Object { -not (Test-VirtualLanInterface -InterfaceAlias $_.InterfaceAlias) } |
      Select-Object -First 1

    if (-not $preferred) {
      $preferred = $candidates | Select-Object -First 1
    }

    if (-not $preferred) {
      throw "Could not auto-detect a usable LAN IPv4 address. Pass -HostIp explicitly."
    }

    return $preferred.IPAddress
  }
}

function Get-DefaultLanIp {
  return Get-NetIPAddress -AddressFamily IPv4 | Select-PreferredLanIp
}

function Assert-DemoHostIp {
  param([string]$IpAddress)

  if (-not (Test-PrivateIPv4 -IpAddress $IpAddress)) {
    throw "HostIp must be a private LAN IPv4 address reachable by the ESP32."
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

  Write-Host "Buddy Core health: http://${HostIp}:8010/health"
  Write-Host "Buddy Core OpenAI base_url: http://${HostIp}:8010/v1"
  Write-Host "XiaoZhi OTA URL: http://${HostIp}:8003/xiaozhi/ota/"
  Write-Host "XiaoZhi WebSocket URL: ws://${HostIp}:8000/xiaozhi/v1/"
  Write-Host "Firmware OTA value, if flashing is needed: CONFIG_OTA_URL=http://${HostIp}:8003/xiaozhi/ota/"
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-PrintLocalDemoUrls -HostIp $HostIp
}
