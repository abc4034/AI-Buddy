param(
  [string]$BindHost = "0.0.0.0",
  [int]$HttpPort = 8003,
  [int]$WebSocketPort = 8000,
  [string]$AdvertiseHost = "",
  [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
  [string]$AudioArtifactDir = "",
  [int]$AudioSessionLimit = 20,
  [string]$VadProvider = "",
  [double]$VadThreshold = 0.5,
  [double]$VadThresholdLow = 0.2,
  [int]$VadMinSilenceMs = 1000,
  [int]$VadWindowSize = 5,
  [int]$VadVoiceVotes = 3,
  [int]$VadPrerollFrames = 10,
  [int]$VadMinTurnFrames = 16,
  [string]$AsrProvider = "",
  [string]$AsrHttpUrl = "",
  [string]$AsrModel = "",
  [string]$AsrApiKey = "",
  [double]$AsrTimeoutSeconds = 60,
  [string]$TtsProvider = "",
  [string]$TtsHttpUrl = "",
  [string]$TtsModel = "",
  [string]$TtsApiKey = "",
  [string]$TtsVoice = "",
  [string]$TtsLanguage = "",
  [double]$TtsTimeoutSeconds = 60,
  [int]$TtsFrameDelayMs = 60,
  [switch]$SendSttToDevice,
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Test-PrivateIPv4 {
  param([string]$IpAddress)

  $parsedIp = $null
  if (-not [System.Net.IPAddress]::TryParse($IpAddress, [ref]$parsedIp)) {
    return $false
  }

  if ($parsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    return $false
  }

  $octets = $IpAddress.Split(".")
  $first = [int]$octets[0]
  $second = [int]$octets[1]

  if ($first -eq 10) {
    return $true
  }

  if (($first -eq 192) -and ($second -eq 168)) {
    return $true
  }

  if (($first -eq 172) -and ($second -ge 16) -and ($second -le 31)) {
    return $true
  }

  return $false
}

function Test-VirtualLanInterface {
  param([string]$InterfaceAlias)

  if ([string]::IsNullOrWhiteSpace($InterfaceAlias)) {
    return $false
  }

  return $InterfaceAlias -match "VMware|VirtualBox|vEthernet|Docker|Loopback|Hyper-V|WSL|Npcap"
}

function Select-PreferredLanIp {
  param(
    [Parameter(ValueFromPipeline = $true)]
    [object]$InputObject
  )

  begin {
    $candidates = @()
  }

  process {
    if ($null -eq $InputObject) {
      return
    }

    if ($InputObject -is [string]) {
      $ipAddress = $InputObject
      $interfaceAlias = ""
    }
    else {
      $ipAddress = $InputObject.IPAddress
      $interfaceAlias = $InputObject.InterfaceAlias
    }

    if (-not [string]::IsNullOrWhiteSpace($ipAddress) -and (Test-PrivateIPv4 -IpAddress $ipAddress)) {
      $candidates += [pscustomobject]@{
        IPAddress = $ipAddress
        InterfaceAlias = $interfaceAlias
      }
    }
  }

  end {
    $preferred = $candidates |
      Where-Object { -not (Test-VirtualLanInterface -InterfaceAlias $_.InterfaceAlias) } |
      Select-Object -First 1

    if (-not $preferred) {
      $preferred = $candidates | Select-Object -First 1
    }

    if (-not $preferred) {
      throw "Could not auto-detect a usable LAN IPv4 address. Pass -AdvertiseHost explicitly."
    }

    return $preferred.IPAddress
  }
}

function Get-DefaultAdvertiseHost {
  return Get-NetIPAddress -AddressFamily IPv4 | Select-PreferredLanIp
}

function Sync-UserEnvironmentVariable {
  param([string]$Name)

  $current = [Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not [string]::IsNullOrWhiteSpace($current)) {
    return
  }

  $userValue = [Environment]::GetEnvironmentVariable($Name, "User")
  if (-not [string]::IsNullOrWhiteSpace($userValue)) {
    [Environment]::SetEnvironmentVariable($Name, $userValue, "Process")
  }
}

function Initialize-GatewayAsrEnvironment {
  foreach ($name in @("ASR_PROVIDER", "ASR_HTTP_URL", "ASR_MODEL", "ASR_API_KEY")) {
    Sync-UserEnvironmentVariable -Name $name
  }
}

function Initialize-GatewayTtsEnvironment {
  foreach ($name in @("TTS_PROVIDER", "TTS_HTTP_URL", "TTS_MODEL", "TTS_API_KEY", "TTS_VOICE", "TTS_LANGUAGE")) {
    Sync-UserEnvironmentVariable -Name $name
  }
}

function Initialize-GatewayVadEnvironment {
  foreach ($name in @("VAD_PROVIDER", "VAD_THRESHOLD", "VAD_THRESHOLD_LOW", "VAD_MIN_SILENCE_MS", "VAD_WINDOW_SIZE", "VAD_VOICE_VOTES", "VAD_PREROLL_FRAMES", "VAD_MIN_TURN_FRAMES")) {
    Sync-UserEnvironmentVariable -Name $name
  }
}

function Invoke-StartBuddyGateway {
  param(
    [string]$BindHost = "0.0.0.0",
    [int]$HttpPort = 8003,
    [int]$WebSocketPort = 8000,
    [string]$AdvertiseHost = "",
    [string]$BuddyCoreBaseUrl = "http://127.0.0.1:8010",
    [string]$AudioArtifactDir = "",
    [int]$AudioSessionLimit = 20,
    [string]$VadProvider = "",
    [double]$VadThreshold = 0.5,
    [double]$VadThresholdLow = 0.2,
    [int]$VadMinSilenceMs = 1000,
    [int]$VadWindowSize = 5,
    [int]$VadVoiceVotes = 3,
    [int]$VadPrerollFrames = 10,
    [int]$VadMinTurnFrames = 16,
    [string]$AsrProvider = "",
    [string]$AsrHttpUrl = "",
    [string]$AsrModel = "",
    [string]$AsrApiKey = "",
    [double]$AsrTimeoutSeconds = 60,
    [string]$TtsProvider = "",
    [string]$TtsHttpUrl = "",
    [string]$TtsModel = "",
    [string]$TtsApiKey = "",
    [string]$TtsVoice = "",
    [string]$TtsLanguage = "",
    [double]$TtsTimeoutSeconds = 60,
    [int]$TtsFrameDelayMs = 60,
    [switch]$SendSttToDevice,
    [string]$CondaEnv = "xiaozhi-env"
  )

  $repoRoot = Get-RepoRoot
  Initialize-GatewayAsrEnvironment
  Initialize-GatewayTtsEnvironment
  Initialize-GatewayVadEnvironment
  if ([string]::IsNullOrWhiteSpace($AdvertiseHost)) {
    $AdvertiseHost = Get-DefaultAdvertiseHost
    Write-Host "Auto-detected gateway advertise host $AdvertiseHost"
  }

  $args = @(
    "run",
    "--no-capture-output",
    "-n",
    $CondaEnv,
    "python",
    "-m",
    "buddy_gateway.server",
    "--host",
    $BindHost,
    "--http-port",
    $HttpPort,
    "--websocket-port",
    $WebSocketPort
  )

  $args += @("--advertise-host", $AdvertiseHost)
  $args += @("--buddy-core-base-url", $BuddyCoreBaseUrl)
  if (-not [string]::IsNullOrWhiteSpace($AudioArtifactDir)) {
    $args += @("--audio-artifact-dir", $AudioArtifactDir)
  }
  if ($AudioSessionLimit -ne 20) {
    $args += @("--audio-session-limit", $AudioSessionLimit)
  }
  if (-not [string]::IsNullOrWhiteSpace($VadProvider)) {
    $args += @("--vad-provider", $VadProvider)
  }
  if ($VadThreshold -ne 0.5) {
    $args += @("--vad-threshold", $VadThreshold)
  }
  if ($VadThresholdLow -ne 0.2) {
    $args += @("--vad-threshold-low", $VadThresholdLow)
  }
  if ($VadMinSilenceMs -ne 1000) {
    $args += @("--vad-min-silence-ms", $VadMinSilenceMs)
  }
  if ($VadWindowSize -ne 5) {
    $args += @("--vad-window-size", $VadWindowSize)
  }
  if ($VadVoiceVotes -ne 3) {
    $args += @("--vad-voice-votes", $VadVoiceVotes)
  }
  if ($VadPrerollFrames -ne 10) {
    $args += @("--vad-preroll-frames", $VadPrerollFrames)
  }
  if ($VadMinTurnFrames -ne 16) {
    $args += @("--vad-min-turn-frames", $VadMinTurnFrames)
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrProvider)) {
    $args += @("--asr-provider", $AsrProvider)
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrHttpUrl)) {
    $args += @("--asr-http-url", $AsrHttpUrl)
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrModel)) {
    $args += @("--asr-model", $AsrModel)
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrApiKey)) {
    $args += @("--asr-api-key", $AsrApiKey)
  }
  if ($AsrTimeoutSeconds -ne 60) {
    $args += @("--asr-timeout-seconds", $AsrTimeoutSeconds)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsProvider)) {
    $args += @("--tts-provider", $TtsProvider)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsHttpUrl)) {
    $args += @("--tts-http-url", $TtsHttpUrl)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsModel)) {
    $args += @("--tts-model", $TtsModel)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsApiKey)) {
    $args += @("--tts-api-key", $TtsApiKey)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsVoice)) {
    $args += @("--tts-voice", $TtsVoice)
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsLanguage)) {
    $args += @("--tts-language", $TtsLanguage)
  }
  if ($TtsTimeoutSeconds -ne 60) {
    $args += @("--tts-timeout-seconds", $TtsTimeoutSeconds)
  }
  if ($TtsFrameDelayMs -ne 60) {
    $args += @("--tts-frame-delay-ms", $TtsFrameDelayMs)
  }
  if ($SendSttToDevice) {
    $args += @("--send-stt-to-device")
  }

  Write-Host "Starting Buddy Device Gateway HTTP $BindHost`:$HttpPort, WebSocket $BindHost`:$WebSocketPort with conda env $CondaEnv"
  Write-Host "Gateway OTA will advertise ws://$AdvertiseHost`:$WebSocketPort/xiaozhi/v1/"
  Write-Host "Gateway debug text loop will call Buddy Core at $BuddyCoreBaseUrl/v1/chat/completions"
  if (-not [string]::IsNullOrWhiteSpace($AsrProvider)) {
    Write-Host "Gateway ASR provider is $AsrProvider"
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrHttpUrl)) {
    Write-Host "Gateway ASR HTTP URL is $AsrHttpUrl"
  }
  if (-not [string]::IsNullOrWhiteSpace($AsrModel)) {
    Write-Host "Gateway ASR model is $AsrModel"
  }
  if ($SendSttToDevice) {
    Write-Host "Gateway will send stt text messages back to connected devices"
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsProvider)) {
    Write-Host "Gateway TTS provider is $TtsProvider"
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsHttpUrl)) {
    Write-Host "Gateway TTS HTTP URL is $TtsHttpUrl"
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsModel)) {
    Write-Host "Gateway TTS model is $TtsModel"
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsVoice)) {
    Write-Host "Gateway TTS voice is $TtsVoice"
  }
  if (-not [string]::IsNullOrWhiteSpace($TtsLanguage)) {
    Write-Host "Gateway TTS language is $TtsLanguage"
  }
  if (-not [string]::IsNullOrWhiteSpace($AudioArtifactDir)) {
    Write-Host "Gateway audio artifacts will be stored under $AudioArtifactDir"
  }
  Write-Host "Gateway audio session retention is $AudioSessionLimit"

  Push-Location $repoRoot
  try {
    & conda @args
  }
  finally {
    Pop-Location
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartBuddyGateway -BindHost $BindHost -HttpPort $HttpPort -WebSocketPort $WebSocketPort -AdvertiseHost $AdvertiseHost -BuddyCoreBaseUrl $BuddyCoreBaseUrl -AudioArtifactDir $AudioArtifactDir -AudioSessionLimit $AudioSessionLimit -VadProvider $VadProvider -VadThreshold $VadThreshold -VadThresholdLow $VadThresholdLow -VadMinSilenceMs $VadMinSilenceMs -VadWindowSize $VadWindowSize -VadVoiceVotes $VadVoiceVotes -VadPrerollFrames $VadPrerollFrames -VadMinTurnFrames $VadMinTurnFrames -AsrProvider $AsrProvider -AsrHttpUrl $AsrHttpUrl -AsrModel $AsrModel -AsrApiKey $AsrApiKey -AsrTimeoutSeconds $AsrTimeoutSeconds -TtsProvider $TtsProvider -TtsHttpUrl $TtsHttpUrl -TtsModel $TtsModel -TtsApiKey $TtsApiKey -TtsVoice $TtsVoice -TtsLanguage $TtsLanguage -TtsTimeoutSeconds $TtsTimeoutSeconds -TtsFrameDelayMs $TtsFrameDelayMs -SendSttToDevice:$SendSttToDevice -CondaEnv $CondaEnv
}
