param(
  [string]$ConfigPath = "",
  [string]$Text = "Hello from the Buddy TTS native queue smoke.",
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $repoRoot "xiaozhi_server\data\.config.yaml"
} elseif (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
  $ConfigPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ConfigPath))
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
  throw "Rendered XiaoZhi config was not found. Run render_xiaozhi_config.ps1 first."
}

Push-Location $repoRoot
try {
  & conda run --no-capture-output -n $CondaEnv python -m integrations.xiaozhi_server.smoke_tts --config $ConfigPath --text $Text
  if ($LASTEXITCODE -ne 0) {
    throw "XiaoZhi TTS smoke failed."
  }
}
finally {
  Pop-Location
}
