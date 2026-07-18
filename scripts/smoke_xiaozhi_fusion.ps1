param(
  [string]$XiaoZhiBaseUrl = "http://127.0.0.1:8003",
  [string]$XiaoZhiWebSocketUrl = "ws://127.0.0.1:8000/xiaozhi/v1/",
  [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
  [string]$DeviceId = "",
  [string]$OpusDirectory = "",
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

function Get-FusionJson {
  param([string]$Uri)

  return Invoke-RestMethod -Uri $Uri -TimeoutSec 5
}

function Assert-FusionHealth {
  param(
    [string]$XiaoZhiBaseUrl,
    [string]$BuddyCoreBaseUrl
  )

  $buddy = Get-FusionJson -Uri "$($BuddyCoreBaseUrl.TrimEnd('/'))/health"
  $xiaozhi = Get-FusionJson -Uri "$($XiaoZhiBaseUrl.TrimEnd('/'))/health"
  if ($buddy.status -ne "ok" -or $xiaozhi.status -ne "ok") {
    throw "Fusion health endpoint did not report ok."
  }
}

function Resolve-FusionOpusDirectory {
  param([string]$OpusDirectory = "")

  $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
  if (-not [string]::IsNullOrWhiteSpace($OpusDirectory)) {
    $resolved = if ([System.IO.Path]::IsPathRooted($OpusDirectory)) {
      [System.IO.Path]::GetFullPath($OpusDirectory)
    }
    else {
      [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OpusDirectory))
    }
    $frames = @(Get-ChildItem -LiteralPath $resolved -Filter "frame-*.opus" -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Length -gt 0 })
    if ($frames.Count -eq 0) {
      throw "The selected voice-loop input directory has no nonempty Opus frames."
    }
    return $resolved
  }

  $captureRoot = Join-Path $repoRoot "data\gateway_audio"
  $candidate = Get-ChildItem -LiteralPath $captureRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Where-Object {
      @(Get-ChildItem -LiteralPath $_.FullName -Filter "frame-*.opus" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -gt 0 }).Count -gt 0
    } |
    Select-Object -First 1
  if (-not $candidate) {
    throw "No captured Opus input was found. Pass -OpusDirectory from a verified hardware capture."
  }
  return [System.IO.Path]::GetFullPath($candidate.FullName)
}

function New-FusionVoiceLoopDeviceId {
  return "software-voice-loop-$([guid]::NewGuid().ToString('N'))"
}

function Invoke-FusionVoiceLoopValidation {
  param(
    [string]$DeviceId,
    [string]$OpusDirectory,
    [string]$XiaoZhiWebSocketUrl,
    [string]$BuddyCoreBaseUrl,
    [string]$CondaEnv
  )

  $names = @(
    "RUN_XIAOZHI_VOICE_LOOP",
    "XIAOZHI_VOICE_LOOP_DEVICE_ID",
    "XIAOZHI_VOICE_LOOP_OPUS_DIR",
    "XIAOZHI_VOICE_LOOP_WS_URL",
    "XIAOZHI_VOICE_LOOP_BUDDY_URL"
  )
  $previous = @{}
  foreach ($name in $names) {
    $previous[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
  }
  try {
    [System.Environment]::SetEnvironmentVariable("RUN_XIAOZHI_VOICE_LOOP", "1", "Process")
    [System.Environment]::SetEnvironmentVariable("XIAOZHI_VOICE_LOOP_DEVICE_ID", $DeviceId, "Process")
    [System.Environment]::SetEnvironmentVariable("XIAOZHI_VOICE_LOOP_OPUS_DIR", $OpusDirectory, "Process")
    [System.Environment]::SetEnvironmentVariable("XIAOZHI_VOICE_LOOP_WS_URL", $XiaoZhiWebSocketUrl, "Process")
    [System.Environment]::SetEnvironmentVariable("XIAOZHI_VOICE_LOOP_BUDDY_URL", $BuddyCoreBaseUrl, "Process")
    $null = @(& conda run -n $CondaEnv python -m pytest tests/xiaozhi_fusion/test_voice_loop.py -q -s)
    if ($LASTEXITCODE -ne 0) {
      throw "The live XiaoZhi voice-loop validator failed."
    }
  }
  finally {
    foreach ($name in $names) {
      [System.Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
    }
  }
  return [pscustomobject]@{
    DeviceId = $DeviceId
    OpusDirectory = $OpusDirectory
    Validated = $true
  }
}

function Invoke-SmokeXiaoZhiFusion {
  param(
    [string]$XiaoZhiBaseUrl = "http://127.0.0.1:8003",
    [string]$XiaoZhiWebSocketUrl = "ws://127.0.0.1:8000/xiaozhi/v1/",
    [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
    [string]$DeviceId = "",
    [string]$OpusDirectory = "",
    [string]$CondaEnv = "xiaozhi-env"
  )

  Assert-FusionHealth -XiaoZhiBaseUrl $XiaoZhiBaseUrl -BuddyCoreBaseUrl $BuddyCoreBaseUrl
  $resolvedInput = Resolve-FusionOpusDirectory -OpusDirectory $OpusDirectory
  if ([string]::IsNullOrWhiteSpace($DeviceId)) {
    $DeviceId = New-FusionVoiceLoopDeviceId
  }
  return Invoke-FusionVoiceLoopValidation -DeviceId $DeviceId -OpusDirectory $resolvedInput -XiaoZhiWebSocketUrl $XiaoZhiWebSocketUrl -BuddyCoreBaseUrl $BuddyCoreBaseUrl -CondaEnv $CondaEnv
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeXiaoZhiFusion -XiaoZhiBaseUrl $XiaoZhiBaseUrl -XiaoZhiWebSocketUrl $XiaoZhiWebSocketUrl -BuddyCoreBaseUrl $BuddyCoreBaseUrl -DeviceId $DeviceId -OpusDirectory $OpusDirectory -CondaEnv $CondaEnv | ConvertTo-Json -Depth 5
}
