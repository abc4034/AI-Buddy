param(
  [string]$ServerDir = "xiaozhi_server",
  [string]$CondaEnv = "xiaozhi-env"
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

function Get-ResolvedXiaoZhiServerDir {
  param([string]$ServerDir)

  $repoRoot = Get-RepoRoot
  $defaultServerDir = Resolve-RepoPath -Path "xiaozhi_server" -RepoRoot $repoRoot
  $resolvedServerDir = Resolve-RepoPath -Path $ServerDir -RepoRoot $repoRoot

  if (-not (Test-IsChildOrSameDirectory -Path $resolvedServerDir -ParentDirectory $defaultServerDir)) {
    throw "ServerDir must resolve under $defaultServerDir"
  }

  if (-not $resolvedServerDir.Equals($defaultServerDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "ServerDir must resolve to the vendored runtime $defaultServerDir"
  }

  return $resolvedServerDir
}

function Assert-XiaoZhiServerPreflight {
  param([string]$ResolvedServerDir)

  if (-not (Test-Path (Join-Path $ResolvedServerDir "app.py"))) {
    throw "XiaoZhi server app.py not found under $ResolvedServerDir."
  }

  if (-not (Test-Path (Join-Path $ResolvedServerDir "core") -PathType Container)) {
    throw "XiaoZhi server core directory not found under $ResolvedServerDir."
  }

  if (-not (Test-Path (Join-Path $ResolvedServerDir "config") -PathType Container)) {
    throw "XiaoZhi server config directory not found under $ResolvedServerDir."
  }

  if (-not (Test-Path (Join-Path $ResolvedServerDir "data\.config.yaml"))) {
    throw "XiaoZhi data\.config.yaml not found. Run .\scripts\render_xiaozhi_config.ps1 first."
  }
}

function Invoke-StartXiaoZhiServer {
  param(
    [string]$ServerDir,
    [string]$CondaEnv = "xiaozhi-env"
  )

  $resolvedServerDir = Get-ResolvedXiaoZhiServerDir -ServerDir $ServerDir
  Assert-XiaoZhiServerPreflight -ResolvedServerDir $resolvedServerDir
  $appPath = [System.IO.Path]::GetFullPath((Join-Path $resolvedServerDir "app.py"))

  Write-Host "Starting XiaoZhi server from $resolvedServerDir with conda env $CondaEnv"
  Write-Host "WebSocket endpoint: ws://<LAN-IP>:8000/xiaozhi/v1/"
  Write-Host "OTA endpoint: http://<LAN-IP>:8003/xiaozhi/ota/"
  Push-Location $resolvedServerDir
  try {
    & conda run --no-capture-output -n $CondaEnv python $appPath
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartXiaoZhiServer -ServerDir $ServerDir -CondaEnv $CondaEnv
}
