param(
  [string]$BindHost = "0.0.0.0",
  [int]$HttpPort = 8003,
  [int]$WebSocketPort = 8000,
  [string]$AdvertiseHost = "",
  [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
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
      throw "Could not auto-detect a usable LAN IPv4 address. Pass -AdvertiseHost explicitly."
    }

    return $preferred.IPAddress
  }
}

function Get-DefaultAdvertiseHost {
  return Get-NetIPAddress -AddressFamily IPv4 | Select-PreferredLanIp
}

function Invoke-StartBuddyGateway {
  param(
    [string]$BindHost = "0.0.0.0",
    [int]$HttpPort = 8003,
    [int]$WebSocketPort = 8000,
    [string]$AdvertiseHost = "",
    [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
    [string]$CondaEnv = "xiaozhi-env"
  )

  $repoRoot = Get-RepoRoot
  if ([string]::IsNullOrWhiteSpace($AdvertiseHost)) {
    $AdvertiseHost = Get-DefaultAdvertiseHost
    Write-Host "Auto-detected gateway advertise host $AdvertiseHost"
  }

  $args = @(
    "run",
    "--no-capture-output",
    "-n",
    $CondaEnv,
    "python",
    "-m",
    "buddy_gateway.server",
    "--host",
    $BindHost,
    "--http-port",
    $HttpPort,
    "--websocket-port",
    $WebSocketPort
  )

  $args += @("--advertise-host", $AdvertiseHost)
  $args += @("--buddy-core-base-url", $BuddyCoreBaseUrl)

  Write-Host "Starting Buddy Device Gateway HTTP $BindHost`:$HttpPort, WebSocket $BindHost`:$WebSocketPort with conda env $CondaEnv"
  Write-Host "Gateway OTA will advertise ws://$AdvertiseHost`:$WebSocketPort/xiaozhi/v1/"
  Write-Host "Gateway debug text loop will call Buddy Core at $BuddyCoreBaseUrl/v1/chat/completions"

  Push-Location $repoRoot
  try {
    & conda @args
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartBuddyGateway -BindHost $BindHost -HttpPort $HttpPort -WebSocketPort $WebSocketPort -AdvertiseHost $AdvertiseHost -BuddyCoreBaseUrl $BuddyCoreBaseUrl -CondaEnv $CondaEnv
}
