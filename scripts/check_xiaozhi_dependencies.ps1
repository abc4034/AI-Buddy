param(
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Invoke-CheckXiaoZhiDependencies {
  param([string]$CondaEnv = "xiaozhi-env")

  $repoRoot = Get-RepoRoot
  $runtimeDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "xiaozhi_server"))
  $repairCommand = "conda run -n xiaozhi-env python -m pip install -r .\xiaozhi_server\requirements.txt"

  try {
    Push-Location $runtimeDir
    & conda run -n $CondaEnv python -m pip check
    if ($LASTEXITCODE -ne 0) {
      throw "python -m pip check failed with exit code $LASTEXITCODE"
    }

    & conda run -n $CondaEnv python -B -c "import websockets; import core.providers.asr.fun_local; import core.providers.llm.openai.openai; import core.providers.tts.edge"
    if ($LASTEXITCODE -ne 0) {
      throw "production provider imports failed with exit code $LASTEXITCODE"
    }

    Write-Host "XiaoZhi dependency check passed"
  }
  catch {
    Write-Host "XiaoZhi dependency check failed: $($_.Exception.Message)"
    Write-Host "Repair command (not run automatically): $repairCommand"
    throw
  }
  finally {
    if ((Get-Location).Path -eq $runtimeDir) {
      Pop-Location
    }
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-CheckXiaoZhiDependencies -CondaEnv $CondaEnv
}
