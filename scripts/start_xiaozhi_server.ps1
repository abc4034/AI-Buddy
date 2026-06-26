param(
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server",
  [string]$CondaEnv = "xiaozhi-esp32-server"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Get-ResolvedXiaoZhiServerDir {
  param([string]$ServerDir)

  if ([System.IO.Path]::IsPathRooted($ServerDir)) {
    return [System.IO.Path]::GetFullPath($ServerDir)
  }

  return [System.IO.Path]::GetFullPath((Join-Path (Get-RepoRoot) $ServerDir))
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
    [string]$CondaEnv = "xiaozhi-esp32-server"
  )

  $resolvedServerDir = Get-ResolvedXiaoZhiServerDir -ServerDir $ServerDir
  Assert-XiaoZhiServerPreflight -ResolvedServerDir $resolvedServerDir

  Write-Host "Starting XiaoZhi server from $resolvedServerDir with conda env $CondaEnv"
  Push-Location $resolvedServerDir
  try {
    & conda run -n $CondaEnv python app.py
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartXiaoZhiServer -ServerDir $ServerDir -CondaEnv $CondaEnv
}
