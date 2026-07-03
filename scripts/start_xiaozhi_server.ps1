param(
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server",
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
  $runRoot = Resolve-RepoPath -Path ".run" -RepoRoot $repoRoot
  $defaultServerDir = Resolve-RepoPath -Path ".run\xiaozhi-esp32-server\main\xiaozhi-server" -RepoRoot $repoRoot
  $resolvedServerDir = Resolve-RepoPath -Path $ServerDir -RepoRoot $repoRoot

  if (-not (Test-IsChildOrSameDirectory -Path $resolvedServerDir -ParentDirectory $runRoot)) {
    throw "ServerDir must resolve under $runRoot"
  }

  if ($resolvedServerDir.Equals($runRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "ServerDir must resolve to a server directory under $runRoot"
  }

  if ($resolvedServerDir.Equals($defaultServerDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $resolvedServerDir
  }

  return $resolvedServerDir
}

function Assert-XiaoZhiServerPreflight {
  param([string]$ResolvedServerDir)

  if (-not (Test-Path (Join-Path $ResolvedServerDir "app.py"))) {
    throw "XiaoZhi server app.py not found. Run .\scripts\setup_xiaozhi_server.ps1 first."
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

  Write-Host "Starting XiaoZhi server from $resolvedServerDir with conda env $CondaEnv"
  Push-Location $resolvedServerDir
  try {
    & conda run --no-capture-output -n $CondaEnv python app.py
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartXiaoZhiServer -ServerDir $ServerDir -CondaEnv $CondaEnv
}
