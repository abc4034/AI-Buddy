param(
  [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
  [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory",
  [string]$Text = "I like apples",
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

function Get-GatewayDebugSessions {
  param([string]$GatewayBaseUrl)

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  return Invoke-JsonHttpRequest -Method Get -Uri "$baseUrl/debug/sessions"
}

function Select-GatewaySession {
  param(
    [object]$DebugPayload,
    [string]$SessionId = ""
  )

  $sessions = @($DebugPayload.sessions)
  if ($sessions.Count -eq 0) {
    throw "No Gateway sessions found. Connect ESP32 or a WebSocket debug client first."
  }

  if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
    $match = $sessions | Where-Object { $_.session_id -eq $SessionId } | Select-Object -First 1
    if (-not $match) {
      throw "Gateway session '$SessionId' was not found."
    }
    return $match
  }

  return $sessions[-1]
}

function Invoke-GatewayTextInjection {
  param(
    [string]$GatewayBaseUrl,
    [string]$SessionId,
    [string]$Text
  )

  if ([string]::IsNullOrWhiteSpace($Text)) {
    throw "Text must not be empty."
  }

  $baseUrl = $GatewayBaseUrl.TrimEnd("/")
  $body = @{ text = $Text } | ConvertTo-Json -Compress
  return Invoke-JsonHttpRequest -Method Post -Uri "$baseUrl/debug/sessions/$SessionId/inject-text" -Body $body -ContentType "application/json"
}

function Invoke-SmokeGatewayTextLoop {
  param(
    [string]$GatewayBaseUrl = "http://127.0.0.1:8003",
    [string]$MemoryBaseUrl = "http://127.0.0.1:8010/memory",
    [string]$Text = "I like apples",
    [string]$SessionId = "",
    [switch]$PassThru
  )

  $debugPayload = Get-GatewayDebugSessions -GatewayBaseUrl $GatewayBaseUrl
  $session = Select-GatewaySession -DebugPayload $debugPayload -SessionId $SessionId
  $result = Invoke-GatewayTextInjection -GatewayBaseUrl $GatewayBaseUrl -SessionId $session.session_id -Text $Text
  $encodedDeviceId = [uri]::EscapeDataString([string]$session.device_id)
  $memoryUrl = "$($MemoryBaseUrl.TrimEnd('/'))?device_id=$encodedDeviceId"

  Write-Host "Session: $($session.session_id)"
  Write-Host "Device: $($session.device_id)"
  Write-Host "Client: $($session.client_id)"
  Write-Host "User text: $Text"
  Write-Host "Assistant: $($result.assistant_text)"
  Write-Host "Memory URL: $memoryUrl"

  if ($PassThru) {
    return $result
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-SmokeGatewayTextLoop -GatewayBaseUrl $GatewayBaseUrl -MemoryBaseUrl $MemoryBaseUrl -Text $Text -SessionId $SessionId | Out-Null
}
