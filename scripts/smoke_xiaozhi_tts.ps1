param(
  [string]$LogPath = "",
  [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

if ($TimeoutSeconds -le 0) {
  throw "TimeoutSeconds must be positive."
}

if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $LogPath = Join-Path ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))) "xiaozhi_server\tmp\server.log"
}

$deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$ttsStarted = $false
$opusSent = $false

while ([System.DateTime]::UtcNow -lt $deadline) {
  if (Test-Path -LiteralPath $LogPath) {
    $lines = Get-Content -LiteralPath $LogPath -Encoding UTF8 -Tail 500 -ErrorAction Stop
    foreach ($line in $lines) {
      if ($line -match "(?i)tts.*(?:start|sentence_start)") {
        $ttsStarted = $true
      }
      if ($line -match "(?i)opus.*(?:[1-9][0-9]*|sent|frame)") {
        $opusSent = $true
      }
    }
  }

  if ($ttsStarted -and $opusSent) {
    Write-Host "XiaoZhi TTS smoke observed native TTS start and nonzero Opus output."
    exit 0
  }

  Start-Sleep -Milliseconds 500
}

throw "XiaoZhi TTS smoke did not observe both native TTS start and nonzero Opus output in the runtime log."
