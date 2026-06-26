param(
  [string]$Destination = ".run\xiaozhi-esp32-server",
  [switch]$Force
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

function Test-IsStrictChildOfDirectory {
  param(
    [string]$Path,
    [string]$ParentDirectory
  )

  $normalizedParent = [System.IO.Path]::GetFullPath($ParentDirectory).TrimEnd("\")
  $normalizedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\")

  if ($normalizedPath.Equals($normalizedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $false
  }

  return $normalizedPath.StartsWith("$normalizedParent\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-XiaoZhiSetupPaths {
  param([string]$Destination)

  $repoRoot = Get-RepoRoot
  $runRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".run"))
  $destinationPath = Resolve-RepoPath -Path $Destination -RepoRoot $repoRoot

  if (-not (Test-IsStrictChildOfDirectory -Path $destinationPath -ParentDirectory $runRoot)) {
    throw "Destination must resolve to a strict child path under $runRoot"
  }

  $runDir = Split-Path -Parent $destinationPath
  $zipPath = [System.IO.Path]::GetFullPath((Join-Path $runDir "xiaozhi-esp32-server-main.zip"))
  $extractDir = [System.IO.Path]::GetFullPath((Join-Path $runDir "xiaozhi-esp32-server-main"))

  if (-not (Test-IsStrictChildOfDirectory -Path $zipPath -ParentDirectory $runRoot)) {
    throw "Zip path must stay under $runRoot"
  }

  if (-not (Test-IsStrictChildOfDirectory -Path $extractDir -ParentDirectory $runRoot)) {
    throw "Extract path must stay under $runRoot"
  }

  return [pscustomobject]@{
    RepoRoot = $repoRoot
    RunRoot = $runRoot
    DestinationPath = $destinationPath
    RunDir = $runDir
    ZipUrl = "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/heads/main.zip"
    ZipPath = $zipPath
    ExtractDir = $extractDir
  }
}

function Invoke-XiaoZhiSetup {
  param(
    [string]$Destination,
    [switch]$Force
  )

  $paths = Get-XiaoZhiSetupPaths -Destination $Destination

  if ((Test-Path -LiteralPath $paths.DestinationPath) -and -not $Force) {
    Write-Host "XiaoZhi server already exists at $($paths.DestinationPath)"
    return
  }

  if (Test-Path -LiteralPath $paths.DestinationPath) {
    Remove-Item -Recurse -Force -LiteralPath $paths.DestinationPath
  }

  if (Test-Path -LiteralPath $paths.ExtractDir) {
    Remove-Item -Recurse -Force -LiteralPath $paths.ExtractDir
  }

  New-Item -ItemType Directory -Force -Path $paths.RunDir | Out-Null
  Write-Host "Downloading $($paths.ZipUrl)"
  Invoke-WebRequest -UseBasicParsing $paths.ZipUrl -OutFile $paths.ZipPath

  Write-Host "Extracting XiaoZhi server"
  Expand-Archive -Force -LiteralPath $paths.ZipPath -DestinationPath $paths.RunDir
  Move-Item -LiteralPath $paths.ExtractDir -Destination $paths.DestinationPath

  $serverDir = Join-Path $paths.DestinationPath "main\xiaozhi-server"
  $dataDir = Join-Path $serverDir "data"
  New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

  Write-Host "Prepared XiaoZhi server at $serverDir"
  Write-Host "Next: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1"
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-XiaoZhiSetup -Destination $Destination -Force:$Force
}
