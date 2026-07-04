param(
  [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
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

function Select-GatewayAudioSession {
  param(
    [object]$DebugPayload,
    [string]$SessionId = ""
  )

  $sessions = @($DebugPayload.sessions)
  if ($sessions.Count -eq 0) {
    throw "No Gateway audio sessions found. Connect ESP32, trigger listen, and speak once first."
  }

  if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
    $match = $sessions | Where-Object { $_.session_id -eq $SessionId } | Select-Object -First 1
    if (-not $match) {
      throw "Gateway audio session '$SessionId' was not found."
    }
    return $match
  }

  return $sessions[-1]
}

function Invoke-GatewayAudioDecode {
  param(
    [string]$GatewayBaseUrl,
    [string]$SessionId
  )

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Post -Uri "$baseUrl/debug/sessions/$SessionId/decode-audio"
}

function Invoke-SmokeGatewayAudioCapture {
  param(
    [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
    [string]$SessionId = "",
    [switch]$PassThru
  )

  $debugPayload = Get-GatewayAudioSessions -GatewayBaseUrl $GatewayBaseUrl
  $session = Select-GatewayAudioSession -DebugPayload $debugPayload -SessionId $SessionId
  $result = Invoke-GatewayAudioDecode -GatewayBaseUrl $GatewayBaseUrl -SessionId $session.session_id

  Write-Host "Session: $($session.session_id)"
  Write-Host "Device: $($session.device_id)"
  Write-Host "Client: $($session.client_id)"
  Write-Host "Opus frames: $($result.opus_frame_count)"
  Write-Host "Decoded frames: $($result.decoded_frame_count)"
  Write-Host "Decode errors: $($result.decode_error_count)"
  Write-Host "WAV path: $($result.wav_path)"
  Write-Host "Audio URL: $($result.audio_url)"

  if ($PassThru) {
    return $result
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeGatewayAudioCapture -GatewayBaseUrl $GatewayBaseUrl -SessionId $SessionId | Out-Null
}
