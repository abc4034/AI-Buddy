param(
  [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
  [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory",
  [string]$SessionId = ""
)

$ErrorActionPreference = "Stop"

try {
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
  $OutputEncoding = [System.Text.UTF8Encoding]::new()
}
catch {
}

function Invoke-JsonHttpRequest {
  param(
    [string]$Method = "Get",
    [string]$Uri,
    $Body = $null,
    [string]$ContentType = ""
  )

  $request = @{
    Method = $Method
    Uri = $Uri
    UseBasicParsing = $true
  }
  if ($null -ne $Body) {
    $request.Body = $Body
  }
  if (-not [string]::IsNullOrWhiteSpace($ContentType)) {
    $request.ContentType = $ContentType
  }

  $response = Invoke-WebRequest @request
  if ($response.RawContentStream) {
    if ($response.RawContentStream.CanSeek) {
      $response.RawContentStream.Position = 0
    }
    $reader = [System.IO.StreamReader]::new($response.RawContentStream, [System.Text.Encoding]::UTF8)
    try {
      $content = $reader.ReadToEnd()
    }
    finally {
      $reader.Dispose()
    }
  }
  else {
    $content = [string]$response.Content
  }

  return $content | ConvertFrom-Json
}

function Get-GatewayAudioSessions {
  param([string]$GatewayBaseUrl)

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Get -Uri "$baseUrl/debug/audio/sessions"
}

function Get-GatewayDebugSessions {
  param([string]$GatewayBaseUrl)

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Get -Uri "$baseUrl/debug/sessions"
}

function Select-GatewayAsrSession {
  param(
    [object]$DebugPayload,
    [object]$AudioPayload,
    [string]$SessionId = ""
  )

  $liveSessions = @($DebugPayload.sessions)
  $audioSessions = @($AudioPayload.sessions)
  if ($liveSessions.Count -eq 0) {
    throw "No live Gateway sessions found. Connect ESP32 to Gateway first."
  }
  if ($audioSessions.Count -eq 0) {
    throw "No Gateway audio sessions found. Trigger listen and speak once first."
  }

  if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
    $liveMatch = $liveSessions | Where-Object { $_.session_id -eq $SessionId } | Select-Object -First 1
    $audioMatch = $audioSessions | Where-Object { $_.session_id -eq $SessionId } | Select-Object -First 1
    if (-not $liveMatch) {
      throw "Gateway live session '$SessionId' was not found."
    }
    if (-not $audioMatch) {
      throw "Gateway audio session '$SessionId' was not found."
    }
    return $liveMatch
  }

  for ($i = $liveSessions.Count - 1; $i -ge 0; $i--) {
    $liveSession = $liveSessions[$i]
    $audioMatch = $audioSessions | Where-Object { $_.session_id -eq $liveSession.session_id } | Select-Object -First 1
    if ($audioMatch) {
      return $liveSession
    }
  }

  throw "No live Gateway session has captured audio. Trigger listen and speak once first."
}

function Invoke-GatewayAsrTranscription {
  param(
    [string]$GatewayBaseUrl,
    [string]$SessionId
  )

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Post -Uri "$baseUrl/debug/sessions/$SessionId/transcribe-audio"
}

function Assert-GatewayAsrResult {
  param([object]$Result)

  if ($Result.status -ne "ok") {
    $message = "Gateway ASR text loop failed with status '$($Result.status)'"
    if (-not [string]::IsNullOrWhiteSpace([string]$Result.error)) {
      $message = "$message`: $($Result.error)"
    }
    throw $message
  }

  if ([string]::IsNullOrWhiteSpace([string]$Result.transcript)) {
    throw "Gateway ASR text loop returned an empty transcript."
  }

  if ([string]::IsNullOrWhiteSpace([string]$Result.assistant_text)) {
    throw "Gateway ASR text loop returned an empty Buddy Core response."
  }
}

function Invoke-SmokeGatewayAsrTextLoop {
  param(
    [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
    [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory",
    [string]$SessionId = "",
    [switch]$PassThru
  )

  $debugPayload = Get-GatewayDebugSessions -GatewayBaseUrl $GatewayBaseUrl
  $audioPayload = Get-GatewayAudioSessions -GatewayBaseUrl $GatewayBaseUrl
  $session = Select-GatewayAsrSession -DebugPayload $debugPayload -AudioPayload $audioPayload -SessionId $SessionId
  $result = Invoke-GatewayAsrTranscription -GatewayBaseUrl $GatewayBaseUrl -SessionId $session.session_id
  Assert-GatewayAsrResult -Result $result
  $encodedDeviceId = [uri]::EscapeDataString([string]$session.device_id)
  $memoryUrl = "$($MemoryBaseUrl.TrimEnd('/'))?device_id=$encodedDeviceId"

  Write-Host "Session: $($session.session_id)"
  Write-Host "Device: $($session.device_id)"
  Write-Host "Client: $($session.client_id)"
  Write-Host "ASR provider: $($result.asr_provider)"
  Write-Host "Transcript: $($result.transcript)"
  Write-Host "Assistant: $($result.assistant_text)"
  Write-Host "Memory URL: $memoryUrl"

  if ($PassThru) {
    return $result
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeGatewayAsrTextLoop -GatewayBaseUrl $GatewayBaseUrl -MemoryBaseUrl $MemoryBaseUrl -SessionId $SessionId | Out-Null
}
