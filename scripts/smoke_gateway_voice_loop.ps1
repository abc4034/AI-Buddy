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
    [string]$Uri
  )

  $response = Invoke-WebRequest -Method $Method -Uri $Uri -UseBasicParsing
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

function Get-GatewayDebugSessions {
  param([string]$GatewayBaseUrl)

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Get -Uri "$baseUrl/debug/sessions"
}

function Get-LatestTurn {
  param(
    [object]$Session,
    [string]$PropertyName
  )

  $turns = @($Session.$PropertyName)
  if ($turns.Count -eq 0) {
    return $null
  }
  return $turns[$turns.Count - 1]
}

function Select-GatewayVoiceLoop {
  param(
    [object]$DebugPayload,
    [string]$SessionId = ""
  )

  $sessions = @($DebugPayload.sessions)
  if ($sessions.Count -eq 0) {
    throw "No Gateway sessions found. Connect ESP32 to Gateway first."
  }

  if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
    $match = $sessions | Where-Object { $_.session_id -eq $SessionId } | Select-Object -First 1
    if (-not $match) {
      throw "Gateway session '$SessionId' was not found."
    }
    $sessions = @($match)
  }

  for ($i = $sessions.Count - 1; $i -ge 0; $i--) {
    $session = $sessions[$i]
    $asrTurns = @($session.asr_turns)
    $ttsTurns = @($session.tts_turns)
    $latestAsrTurn = Get-LatestTurn -Session $session -PropertyName "asr_turns"
    if ($latestAsrTurn -and $latestAsrTurn.status -ne "ok") {
      $message = "Gateway ASR turn '$($latestAsrTurn.turn_id)' failed with status '$($latestAsrTurn.status)'"
      if (-not [string]::IsNullOrWhiteSpace([string]$latestAsrTurn.error)) {
        $message = "$message`: $($latestAsrTurn.error)"
      }
      throw $message
    }
    if ($latestAsrTurn) {
      $matchingLatestTtsTurn = $ttsTurns |
        Where-Object {
          $_.status -eq "ok" -and
          [int]$_.audio_frame_count -gt 0 -and
          [string]$_.asr_turn_id -eq [string]$latestAsrTurn.turn_id
        } |
        Select-Object -Last 1
      if (-not $matchingLatestTtsTurn) {
        $latestTtsTurn = Get-LatestTurn -Session $session -PropertyName "tts_turns"
        $message = "Gateway ASR turn '$($latestAsrTurn.turn_id)' has no matching successful TTS turn."
        if ($latestTtsTurn -and -not [string]::IsNullOrWhiteSpace([string]$latestTtsTurn.error)) {
          $message = "$message`: $($latestTtsTurn.error)"
        }
        elseif ($latestTtsTurn -and -not [string]::IsNullOrWhiteSpace([string]$latestTtsTurn.asr_turn_id)) {
          $message = "$message Latest TTS targets ASR turn '$($latestTtsTurn.asr_turn_id)'."
        }
        throw $message
      }
    }

    for ($j = $ttsTurns.Count - 1; $j -ge 0; $j--) {
      $ttsTurn = $ttsTurns[$j]
      if ($ttsTurn.status -ne "ok" -or [int]$ttsTurn.audio_frame_count -le 0) {
        continue
      }
      $asrTurn = $asrTurns |
        Where-Object { $_.status -eq "ok" -and [string]$_.turn_id -eq [string]$ttsTurn.asr_turn_id } |
        Select-Object -First 1
      if ($asrTurn) {
        return [pscustomobject]@{
          Session = $session
          AsrTurn = $asrTurn
          TtsTurn = $ttsTurn
        }
      }
    }
  }

  throw "No Gateway session has a successful matched ASR and TTS turn. Speak to ESP32 once and wait for playback."
}

function Assert-GatewayVoiceLoop {
  param(
    [object]$AsrTurn,
    [object]$TtsTurn
  )

  if (-not $AsrTurn) {
    throw "Selected Gateway session has no ASR turn."
  }
  if ($AsrTurn.status -ne "ok") {
    $message = "Gateway ASR turn failed with status '$($AsrTurn.status)'"
    if (-not [string]::IsNullOrWhiteSpace([string]$AsrTurn.error)) {
      $message = "$message`: $($AsrTurn.error)"
    }
    throw $message
  }
  if ([string]::IsNullOrWhiteSpace([string]$AsrTurn.transcript)) {
    throw "Gateway ASR turn has an empty transcript."
  }
  if ([string]::IsNullOrWhiteSpace([string]$AsrTurn.assistant_text)) {
    throw "Gateway ASR turn has an empty Buddy Core response."
  }
  if ([string]::IsNullOrWhiteSpace([string]$AsrTurn.turn_id)) {
    throw "Gateway ASR turn has no turn_id; cannot pair the TTS turn."
  }

  if (-not $TtsTurn) {
    throw "Selected Gateway session has no TTS turn."
  }
  if ($TtsTurn.status -ne "ok") {
    $message = "Gateway TTS turn failed with status '$($TtsTurn.status)'"
    if (-not [string]::IsNullOrWhiteSpace([string]$TtsTurn.error)) {
      $message = "$message`: $($TtsTurn.error)"
    }
    throw $message
  }
  if ([string]::IsNullOrWhiteSpace([string]$TtsTurn.asr_turn_id)) {
    throw "Gateway TTS turn has no asr_turn_id; cannot verify it matches ASR turn '$($AsrTurn.turn_id)'."
  }
  if ([string]$TtsTurn.asr_turn_id -ne [string]$AsrTurn.turn_id) {
    throw "Gateway TTS turn asr_turn_id '$($TtsTurn.asr_turn_id)' does not match ASR turn_id '$($AsrTurn.turn_id)'."
  }
  if ([int]$TtsTurn.audio_frame_count -le 0) {
    throw "Gateway TTS turn did not send any Opus frames."
  }
}

function Invoke-SmokeGatewayVoiceLoop {
  param(
    [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
    [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory",
    [string]$SessionId = "",
    [switch]$PassThru
  )

  $debugPayload = Get-GatewayDebugSessions -GatewayBaseUrl $GatewayBaseUrl
  $voiceLoop = Select-GatewayVoiceLoop -DebugPayload $debugPayload -SessionId $SessionId
  $session = $voiceLoop.Session
  $asrTurn = $voiceLoop.AsrTurn
  $ttsTurn = $voiceLoop.TtsTurn
  Assert-GatewayVoiceLoop -AsrTurn $asrTurn -TtsTurn $ttsTurn

  $encodedDeviceId = [uri]::EscapeDataString([string]$session.device_id)
  $memoryUrl = "$($MemoryBaseUrl.TrimEnd('/'))?device_id=$encodedDeviceId"

  Write-Host "Session: $($session.session_id)"
  Write-Host "Device: $($session.device_id)"
  Write-Host "Client: $($session.client_id)"
  Write-Host "Transcript: $($asrTurn.transcript)"
  Write-Host "Assistant: $($asrTurn.assistant_text)"
  Write-Host "TTS provider: $($ttsTurn.provider)"
  Write-Host "TTS frames sent: $($ttsTurn.audio_frame_count)"
  Write-Host "Memory URL: $memoryUrl"

  if ($PassThru) {
    return [pscustomobject]@{
      Session = $session
      AsrTurn = $asrTurn
      TtsTurn = $ttsTurn
      MemoryUrl = $memoryUrl
    }
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeGatewayVoiceLoop -GatewayBaseUrl $GatewayBaseUrl -MemoryBaseUrl $MemoryBaseUrl -SessionId $SessionId | Out-Null
}
