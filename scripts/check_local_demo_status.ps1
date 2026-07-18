param(
  [string]$ConfigPath = "xiaozhi_server\data\.config.yaml",
  [string]$ServerDir = "xiaozhi_server",
  [string]$RuntimeStatePath = ""
)

$ErrorActionPreference = "Stop"

function Test-ListeningPort {
  param([int]$Port)

  return [bool](Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { [int]$_.LocalPort -eq $Port } |
    Select-Object -First 1)
}

function Get-PortOwnership {
  param([int]$Port)

  $connection = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { [int]$_.LocalPort -eq $Port } |
    Select-Object -First 1
  if (-not $connection) {
    return $null
  }
  $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $connection.OwningProcess) -ErrorAction SilentlyContinue
  return [pscustomobject]@{
    ProcessId = [int]$connection.OwningProcess
    ExecutablePath = if ($process) { [string]$process.ExecutablePath } else { "" }
    Known = [bool]$process
  }
}

function Test-ConfigFlag {
  param(
    [string]$Text,
    [string]$Pattern
  )

  return $Text -match [regex]::Escape($Pattern)
}

function Get-RecentFusionSessions {
  try {
    $payload = Invoke-RestMethod -Uri "http://127.0.0.1:8003/debug/sessions" -TimeoutSec 2
    return @($payload.sessions | Select-Object -Last 5 | ForEach-Object {
      [pscustomobject]@{ SessionId = $_.session_id; State = $_.state; EventCount = @($_.events).Count }
    })
  }
  catch {
    return @()
  }
}

function Get-FusionProvenanceState {
  $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
  $manifest = Join-Path $repoRoot "third_party\xiaozhi-esp32-server\PATCH_MANIFEST.json"
  $state = "unavailable"
  if ((Get-Command conda -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    $null = @(& conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance verify 2>$null)
    $state = if ($LASTEXITCODE -eq 0) { "verified" } else { "failed" }
  }
  return [pscustomobject]@{
    ManifestPresent = Test-Path -LiteralPath $manifest -PathType Leaf
    Verification = $state
  }
}

. (Join-Path $PSScriptRoot "fusion_process_helpers.ps1")

function Resolve-FusionStatusRuntimePath {
  param([string]$RuntimeStatePath = "")

  $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
  if ([string]::IsNullOrWhiteSpace($RuntimeStatePath)) {
    return Join-Path $repoRoot "tmp\runtime\buddy-fusion.json"
  }
  if ([System.IO.Path]::IsPathRooted($RuntimeStatePath)) {
    return [System.IO.Path]::GetFullPath($RuntimeStatePath)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $RuntimeStatePath))
}

function Test-FusionServiceOwnership {
  param(
    [object]$Service,
    [string]$CondaEnv = "xiaozhi-env"
  )

  try {
    $ports = @($Service.Ports | ForEach-Object { [int]$_ })
    $currentPid = Resolve-FusionPortOwnerPid -Ports $ports
    return (
      $currentPid -eq [int]$Service.ListenerPid -and
      (Test-FusionProcessIdentity -ProcessId $currentPid -ExpectedIdentity ([string]$Service.ExpectedIdentity) -ExpectedCommandMarker ([string]$Service.ExpectedCommandMarker) -ExpectedCommandRoot ([string]$Service.ExpectedCommandRoot) -CondaEnv $CondaEnv)
    )
  }
  catch {
    return $false
  }
}

function Get-FusionRuntimeStateStatus {
  param(
    [string]$RuntimeStatePath = "",
    [string]$CondaEnv = "xiaozhi-env"
  )

  $path = Resolve-FusionStatusRuntimePath -RuntimeStatePath $RuntimeStatePath
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    $anyListening = @(@(8000, 8003, 8010) | Where-Object { Test-ListeningPort -Port $_ }).Count -gt 0
    return [pscustomobject]@{
      Path = $path
      Exists = $false
      Status = if ($anyListening) { "unmanaged" } else { "stopped" }
      BuddyCoreOwned = $false
      XiaoZhiOwned = $false
    }
  }

  try {
    $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ([int]$state.SchemaVersion -ne 2 -or $null -eq $state.BuddyCore -or $null -eq $state.XiaoZhi) {
      throw "incomplete state"
    }
    $buddyOwned = Test-FusionServiceOwnership -Service $state.BuddyCore -CondaEnv $CondaEnv
    $xiaozhiOwned = Test-FusionServiceOwnership -Service $state.XiaoZhi -CondaEnv $CondaEnv
    return [pscustomobject]@{
      Path = $path
      Exists = $true
      Status = if ($buddyOwned -and $xiaozhiOwned) { "owned" } else { "mismatch" }
      BuddyCoreOwned = $buddyOwned
      XiaoZhiOwned = $xiaozhiOwned
    }
  }
  catch {
    return [pscustomobject]@{
      Path = $path
      Exists = $true
      Status = "invalid"
      BuddyCoreOwned = $false
      XiaoZhiOwned = $false
    }
  }
}

function Invoke-CheckLocalDemoStatus {
  param(
    [string]$ConfigPath = "xiaozhi_server\data\.config.yaml",
    [string]$ServerDir = "xiaozhi_server",
    [string]$RuntimeStatePath = ""
  )

  $configText = if (Test-Path -LiteralPath $ConfigPath) { Get-Content -LiteralPath $ConfigPath -Raw } else { "" }
  $buddyProviderPath = Join-Path $ServerDir "core\providers\llm\buddy_core\buddy_core.py"
  $legacyProviderPath = Join-Path $ServerDir "core\providers\llm\openai\openai.py"
  $connectionPath = Join-Path $ServerDir "core\connection.py"
  $providerText = if (Test-Path -LiteralPath $buddyProviderPath) { Get-Content -LiteralPath $buddyProviderPath -Raw } elseif (Test-Path -LiteralPath $legacyProviderPath) { Get-Content -LiteralPath $legacyProviderPath -Raw } else { "" }
  $connectionText = if (Test-Path -LiteralPath $connectionPath) { Get-Content -LiteralPath $connectionPath -Raw } else { "" }
  $ownership = [ordered]@{}
  foreach ($port in @(8000, 8003, 8010)) {
    $ownership[[string]$port] = Get-PortOwnership -Port $port
  }

  [pscustomobject]@{
    Ports = [ordered]@{
      "8000" = Test-ListeningPort -Port 8000
      "8003" = Test-ListeningPort -Port 8003
      "8010" = Test-ListeningPort -Port 8010
    }
    Ownership = $ownership
    Config = [ordered]@{
      Exists = Test-Path -LiteralPath $ConfigPath
      BuddyCoreLLM = Test-ConfigFlag -Text $configText -Pattern "BuddyCoreLLM"
      BaseUrl8010 = ($configText -match "base_url:\s+http://.+:8010(?:/v1)?")
      ForwardDeviceMetadata = Test-ConfigFlag -Text $configText -Pattern "forward_device_metadata: true"
      MemoryDisabled = Test-ConfigFlag -Text $configText -Pattern "Memory: nomem"
      IntentDisabled = Test-ConfigFlag -Text $configText -Pattern "Intent: nointent"
      ToolsDisabled = ($configText -match "tools:\s*\r?\n\s*enable:\s*false")
      ReportingDisabled = ($configText -match "report:\s*\r?\n\s*enable:\s*false")
    }
    Providers = [ordered]@{
      ASR = if ($configText -match "ASR:\s+([^\r\n]+)") { $Matches[1].Trim() } else { "" }
      TTS = if ($configText -match "TTS:\s+([^\r\n]+)") { $Matches[1].Trim() } else { "" }
    }
    RuntimePatch = [ordered]@{
      ProviderMetadata = (Test-ConfigFlag -Text $providerText -Pattern "device_id")
      ConnectionMetadata = (
        (Test-ConfigFlag -Text $connectionText -Pattern "client_id") -or
        (Test-ConfigFlag -Text $connectionText -Pattern "client-id")
      )
    }
    RuntimeState = Get-FusionRuntimeStateStatus -RuntimeStatePath $RuntimeStatePath
    Provenance = Get-FusionProvenanceState
    RecentSessions = Get-RecentFusionSessions
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-CheckLocalDemoStatus -ConfigPath $ConfigPath -ServerDir $ServerDir -RuntimeStatePath $RuntimeStatePath | ConvertTo-Json -Depth 6
}
