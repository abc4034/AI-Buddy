param(
  [string]$HostIp = "",
  [string]$Output = ""
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Resolve-RepoPath {
  param(
    [string]$Path,
    [string]$RepoRoot = (Get-RepoRoot)
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }

  return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Test-IsChildOrSameDirectory {
  param(
    [string]$Path,
    [string]$ParentDirectory
  )

  $normalizedParent = [System.IO.Path]::GetFullPath($ParentDirectory).TrimEnd("\")
  $normalizedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\")

  if ($normalizedPath.Equals($normalizedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $true
  }

  return $normalizedPath.StartsWith("$normalizedParent\", [System.StringComparison]::OrdinalIgnoreCase)
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

function Resolve-XiaoZhiConfigOutputPath {
  param([string]$Output)

  $repoRoot = Get-RepoRoot
  $allowedDataDir = Resolve-RepoPath -Path ".run\xiaozhi-esp32-server\main\xiaozhi-server\data" -RepoRoot $repoRoot

  if ([string]::IsNullOrWhiteSpace($Output)) {
    return ""
  }

  $resolvedOutput = Resolve-RepoPath -Path $Output -RepoRoot $repoRoot
  $resolvedParent = Split-Path -Parent $resolvedOutput

  if (-not ($resolvedParent.Equals($allowedDataDir, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Output must resolve under $allowedDataDir"
  }

  return $resolvedOutput
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
    $HostIp = Assert-DemoHostIp -IpAddress $HostIp
  }

  $Output = Resolve-XiaoZhiConfigOutputPath -Output $Output
  $argsList = Get-RenderXiaoZhiConfigArguments -HostIp $HostIp -Output $Output
  Write-Host "Rendering XiaoZhi config for host IP $HostIp"
  & py @argsList
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-RenderXiaoZhiConfig -HostIp $HostIp -Output $Output
}
