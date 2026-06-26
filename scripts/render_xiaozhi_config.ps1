param(
  [string]$HostIp = "",
  [string]$Output = ""
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

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
    throw "HostIp must be a private LAN IPv4 address."
  }

  return $IpAddress
}

function Get-RenderXiaoZhiConfigArguments {
  param(
    [string]$HostIp,
    [string]$Output
  )

  $argsList = @(
    "-3.10",
    "-m",
    "integrations.xiaozhi_server.render_config",
    "--host-ip",
    $HostIp,
    "--repo-root",
    (Get-RepoRoot)
  )

  if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $argsList += @("--output", $Output)
  }

  return $argsList
}

function Invoke-RenderXiaoZhiConfig {
  param(
    [string]$HostIp,
    [string]$Output
  )

  if ([string]::IsNullOrWhiteSpace($HostIp)) {
    $HostIp = Get-DefaultLanIp
  }
  else {
    $HostIp = Assert-PrivateLanIp -IpAddress $HostIp
  }

  $argsList = Get-RenderXiaoZhiConfigArguments -HostIp $HostIp -Output $Output
  Write-Host "Rendering XiaoZhi config for host IP $HostIp"
  & py @argsList
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-RenderXiaoZhiConfig -HostIp $HostIp -Output $Output
}
