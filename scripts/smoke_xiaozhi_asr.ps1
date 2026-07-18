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

$recognizedTextLabel = -join @([char]0x8BC6, [char]0x522B, [char]0x6587, [char]0x672C)
$recognizedTextPattern = [System.Text.RegularExpressions.Regex]::Escape($recognizedTextLabel)
$transcriptPattern = "(?i)(?:transcript|recognized text|asr text|$recognizedTextPattern)\s*(?:[:=]|\uFF1A)\s*(?<transcript>.+)$"
$deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$deviceId = $null
$transcript = $null

while ([System.DateTime]::UtcNow -lt $deadline) {
  if (Test-Path -LiteralPath $LogPath) {
    $lines = Get-Content -LiteralPath $LogPath -Encoding UTF8 -Tail 500 -ErrorAction Stop
    foreach ($line in $lines) {
      if (-not $deviceId -and $line -match "(?i)(?:device[-_ ]?id|client[-_ ]?id)\D*(?<device>(?:[0-9a-f]{2}:){5}[0-9a-f]{2})") {
        $deviceId = $Matches.device
      }
      if (-not $transcript -and $line -match $transcriptPattern) {
        $transcript = $Matches.transcript.Trim()
      }
    }
  }

  if ($deviceId -and -not [string]::IsNullOrWhiteSpace($transcript)) {
    Write-Host "XiaoZhi ASR smoke passed for device $deviceId with a non-empty transcript."
    exit 0
  }

  Start-Sleep -Milliseconds 500
}

throw "XiaoZhi ASR smoke did not observe both a real device ID and a non-empty transcript in the runtime log."
