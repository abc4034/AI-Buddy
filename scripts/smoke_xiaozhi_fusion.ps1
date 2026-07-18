param(
  [string]$XiaoZhiBaseUrl = "http://127.0.0.1:8003",
  [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
  [string]$DeviceId = ""
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

function Get-FusionVoiceSession {
  param(
    [string]$XiaoZhiBaseUrl,
    [string]$DeviceId = ""
  )

  $payload = Get-FusionJson -Uri "$($XiaoZhiBaseUrl.TrimEnd('/'))/debug/sessions"
  $sessions = @($payload.sessions)
  if (-not [string]::IsNullOrWhiteSpace($DeviceId)) {
    $sessions = @($sessions | Where-Object { $_.device_id -eq $DeviceId })
  }
  foreach ($session in @($sessions | Select-Object -Last 20)) {
    $types = @($session.events | ForEach-Object { $_.type })
    if ($types -contains "tts_start" -and $types -contains "tts_stop") {
      return $session
    }
  }
  throw "No completed XiaoZhi TTS session was found. Run the software voice-loop test or speak to the device first."
}

function Invoke-SmokeXiaoZhiFusion {
  param(
    [string]$XiaoZhiBaseUrl = "http://127.0.0.1:8003",
    [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
    [string]$DeviceId = ""
  )

  Assert-FusionHealth -XiaoZhiBaseUrl $XiaoZhiBaseUrl -BuddyCoreBaseUrl $BuddyCoreBaseUrl
  $session = Get-FusionVoiceSession -XiaoZhiBaseUrl $XiaoZhiBaseUrl -DeviceId $DeviceId
  return [pscustomobject]@{ SessionId = $session.session_id; State = $session.state; VoiceLoop = "observed" }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeXiaoZhiFusion -XiaoZhiBaseUrl $XiaoZhiBaseUrl -BuddyCoreBaseUrl $BuddyCoreBaseUrl -DeviceId $DeviceId | ConvertTo-Json -Depth 5
}
