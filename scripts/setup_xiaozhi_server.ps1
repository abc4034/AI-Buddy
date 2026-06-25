param(
  [string]$Destination = ".run\xiaozhi-esp32-server",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".run"))
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$resolvedRunRoot = (Resolve-Path -LiteralPath $runRoot).Path

function Resolve-RepoPath {
  param([string]$Path)

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }

  return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Test-IsUnderDirectory {
  param(
    [string]$Path,
    [string]$AllowedRoot
  )

  $normalizedRoot = $AllowedRoot.TrimEnd("\")
  $normalizedPath = $Path.TrimEnd("\")

  if ($normalizedPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $true
  }

  return $normalizedPath.StartsWith("$normalizedRoot\", [System.StringComparison]::OrdinalIgnoreCase)
}

$zipUrl = "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/heads/main.zip"
$destinationPath = Resolve-RepoPath $Destination

if (-not (Test-IsUnderDirectory -Path $destinationPath -AllowedRoot $resolvedRunRoot)) {
  throw "Destination must resolve under $resolvedRunRoot"
}

$runDir = Split-Path -Parent $destinationPath
$zipPath = Join-Path $runDir "xiaozhi-esp32-server-main.zip"
$extractDir = Join-Path $runDir "xiaozhi-esp32-server-main"

if ((Test-Path $destinationPath) -and -not $Force) {
  Write-Host "XiaoZhi server already exists at $destinationPath"
  exit 0
}

if (Test-Path $destinationPath) {
  Remove-Item -Recurse -Force -LiteralPath $destinationPath
}
if (Test-Path $extractDir) {
  Remove-Item -Recurse -Force -LiteralPath $extractDir
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Write-Host "Downloading $zipUrl"
Invoke-WebRequest -UseBasicParsing $zipUrl -OutFile $zipPath

Write-Host "Extracting XiaoZhi server"
Expand-Archive -Force -LiteralPath $zipPath -DestinationPath $runDir
Move-Item -LiteralPath $extractDir -Destination $destinationPath

$serverDir = Join-Path $destinationPath "main\xiaozhi-server"
$dataDir = Join-Path $serverDir "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

Write-Host "Prepared XiaoZhi server at $serverDir"
Write-Host "Next: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1"
