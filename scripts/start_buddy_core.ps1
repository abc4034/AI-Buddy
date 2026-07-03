param(
  [int]$Port = 8010,
  [string]$CondaEnv = "xiaozhi-env"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $PSCommandPath
$legacyScript = Join-Path $scriptDir "start_buddy_brain.ps1"

. $legacyScript

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StartBuddyCore -Port $Port -CondaEnv $CondaEnv
}
