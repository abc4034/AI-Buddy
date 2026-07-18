param(
  [string]$DatabasePath = "data\buddy_memory.db",
  [string]$XiaoZhiConfigPath = "xiaozhi_server\data\.config.yaml",
  [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"

function Get-DefaultBackupRoot {
  $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
  Join-Path "backups\local-demo" $timestamp
}

function Copy-IfExists {
  param(
    [string]$Source,
    [string]$Destination
  )

  if (Test-Path -LiteralPath $Source) {
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    return (Resolve-Path -LiteralPath $Destination).Path
  }

  return $null
}

function Invoke-BackupLocalDemoData {
  param(
    [string]$DatabasePath = "data\buddy_memory.db",
    [string]$XiaoZhiConfigPath = "xiaozhi_server\data\.config.yaml",
    [string]$BackupRoot = ""
  )

  if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Get-DefaultBackupRoot
  }

  New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

  $dbBackup = Copy-IfExists -Source $DatabasePath -Destination (Join-Path $BackupRoot "buddy_memory.db")
  $configBackup = Copy-IfExists -Source $XiaoZhiConfigPath -Destination (Join-Path $BackupRoot "xiaozhi.config.yaml")

  [pscustomobject]@{
    BackupRoot = (Resolve-Path -LiteralPath $BackupRoot).Path
    DatabaseBackup = $dbBackup
    XiaoZhiConfigBackup = $configBackup
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-BackupLocalDemoData -DatabasePath $DatabasePath -XiaoZhiConfigPath $XiaoZhiConfigPath -BackupRoot $BackupRoot |
    ConvertTo-Json -Depth 5
}
