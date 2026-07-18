param(
  [string[]]$Ports = @("8000", "8003", "8010"),
  [string]$RuntimeStatePath = "",
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function ConvertTo-PortList {
  param([object[]]$Ports = @("8000", "8003", "8010"))

  $portList = @()
  foreach ($port in @($Ports)) {
    foreach ($part in ([string]$port -split ",")) {
      $trimmed = $part.Trim()
      if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
        $portList += [int]$trimmed
      }
    }
  }
  return @($portList | Sort-Object -Unique)
}

function Get-LocalDemoListenerProcesses {
  param([object[]]$Ports = @("8000", "8003", "8010"))

  $portList = ConvertTo-PortList -Ports $Ports
  return @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $portList -contains [int]$_.LocalPort } |
    Group-Object OwningProcess |
    ForEach-Object {
      [pscustomobject]@{
        ProcessId = [int]$_.Name
        Ports = @($_.Group | ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique)
      }
    })
}

function Get-DefaultFusionRuntimeStatePath {
  $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
  return Join-Path $repoRoot "tmp\runtime\buddy-fusion.json"
}

function Resolve-LocalRuntimeStatePath {
  param([string]$RuntimeStatePath = "")

  if ([string]::IsNullOrWhiteSpace($RuntimeStatePath)) {
    return Get-DefaultFusionRuntimeStatePath
  }
  if ([System.IO.Path]::IsPathRooted($RuntimeStatePath)) {
    return [System.IO.Path]::GetFullPath($RuntimeStatePath)
  }
  return [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) $RuntimeStatePath))
}

function Test-FusionProcessIdentity {
  param(
    [int]$ProcessId,
    [string]$ExpectedIdentity,
    [string]$CondaEnv
  )

  if (-not [System.IO.Path]::IsPathRooted($ExpectedIdentity)) {
    return $false
  }
  $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction SilentlyContinue
  if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) {
    return $false
  }
  $environmentPattern = '(?i)(?:[\\/]envs)?[\\/]'+ [regex]::Escape($CondaEnv) + '([\\/]|$)'
  return ([string]$process.ExecutablePath -match $environmentPattern) -and ([string]$process.CommandLine -like "*$ExpectedIdentity*")
}

function Stop-FusionOwnedProcess {
  param(
    [int]$ProcessId,
    [string]$ExpectedIdentity,
    [string]$CondaEnv = "xiaozhi-env",
    [switch]$WhatIf
  )

  $existing = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $existing) {
    return $false
  }
  if (-not (Test-FusionProcessIdentity -ProcessId $ProcessId -ExpectedIdentity $ExpectedIdentity -CondaEnv $CondaEnv)) {
    throw "Refusing to stop PID $ProcessId because its runtime identity is unknown."
  }
  if (-not $WhatIf) {
    Stop-Process -Id $ProcessId -Force
  }
  return $true
}

function Wait-PortsReleased {
  param(
    [int[]]$Ports,
    [int]$TimeoutSeconds = 15
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
      Where-Object { $Ports -contains [int]$_.LocalPort })
    if ($listeners.Count -eq 0) {
      return
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)
  throw "Ports were not released: $($Ports -join ', ')."
}

. (Join-Path $PSScriptRoot "fusion_process_helpers.ps1")

function Stop-FusionService {
  param(
    [object]$Service,
    [string]$CondaEnv,
    [switch]$WhatIf
  )

  $ports = @($Service.Ports | ForEach-Object { [int]$_ })
  $currentListenerPid = Resolve-FusionPortOwnerPid -Ports $ports
  if ($currentListenerPid -ne [int]$Service.ListenerPid) {
    throw "Refusing to stop PID $($Service.ListenerPid) because it no longer owns the recorded ports."
  }
  [void](Stop-FusionOwnedProcess -ProcessId ([int]$Service.ListenerPid) -ExpectedIdentity ([string]$Service.ExpectedIdentity) -ExpectedCommandMarker ([string]$Service.ExpectedCommandMarker) -ExpectedCommandRoot ([string]$Service.ExpectedCommandRoot) -CondaEnv $CondaEnv -WhatIf:$WhatIf)
  if (-not $WhatIf) {
    Wait-FusionPortsReleased -Ports $ports
  }

  $wrapperId = [int]$Service.WrapperPid
  if ($wrapperId -gt 0 -and $wrapperId -ne [int]$Service.ListenerPid) {
    [void](Stop-FusionWrapperProcess -ProcessId $wrapperId -ExpectedCommandMarker ([string]$Service.ExpectedCommandMarker) -ExpectedCommandRoot ([string]$Service.ExpectedCommandRoot) -WhatIf:$WhatIf)
  }
}

function Invoke-StopLocalDemo {
  param(
    [object[]]$Ports = @("8000", "8003", "8010"),
    [string]$RuntimeStatePath = "",
    [string]$CondaEnv = "xiaozhi-env",
    [switch]$WhatIf
  )

  $statePath = Resolve-LocalRuntimeStatePath -RuntimeStatePath $RuntimeStatePath
  if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "Refusing to stop listeners without an owned fusion runtime state file."
  }
  $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
  if ([int]$state.SchemaVersion -ne 2 -or $null -eq $state.XiaoZhi -or $null -eq $state.BuddyCore) {
    throw "Fusion runtime state is incomplete; no process was stopped."
  }

  Stop-FusionService -Service $state.XiaoZhi -CondaEnv $CondaEnv -WhatIf:$WhatIf
  Stop-FusionService -Service $state.BuddyCore -CondaEnv $CondaEnv -WhatIf:$WhatIf
  if (-not $WhatIf) {
    Remove-Item -LiteralPath $statePath -Force
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StopLocalDemo -Ports $Ports -RuntimeStatePath $RuntimeStatePath -WhatIf:$WhatIf
}
