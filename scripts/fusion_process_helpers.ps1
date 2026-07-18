$ErrorActionPreference = "Stop"

function Test-FusionLiteralContains {
  param(
    [string]$Text,
    [string]$Value
  )

  if ([string]::IsNullOrWhiteSpace($Text) -or [string]::IsNullOrWhiteSpace($Value)) {
    return $false
  }
  return $Text.IndexOf($Value, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Resolve-FusionPortOwnerPid {
  param([int[]]$Ports)

  $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $Ports -contains [int]$_.LocalPort })
  $owners = @()
  foreach ($port in $Ports) {
    $matches = @($connections | Where-Object { [int]$_.LocalPort -eq $port })
    if ($matches.Count -ne 1 -or -not $matches[0].OwningProcess) {
      throw "Unknown listener owner for required port $port."
    }
    $owners += [int]$matches[0].OwningProcess
  }
  $owners = @($owners | Sort-Object -Unique)
  if ($owners.Count -ne 1) {
    throw "Required ports must have the same listener PID."
  }
  return [int]$owners[0]
}

function Test-FusionProcessIdentity {
  param(
    [int]$ProcessId,
    [string]$ExpectedIdentity,
    [string]$ExpectedCommandMarker = "",
    [string]$ExpectedCommandRoot = "",
    [string]$CondaEnv = "xiaozhi-env"
  )

  if (-not [System.IO.Path]::IsPathRooted($ExpectedIdentity)) {
    return $false
  }
  if ([string]::IsNullOrWhiteSpace($ExpectedCommandMarker)) {
    $ExpectedCommandMarker = $ExpectedIdentity
  }
  if ([string]::IsNullOrWhiteSpace($ExpectedCommandRoot)) {
    $ExpectedCommandRoot = $ExpectedIdentity
  }
  $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction SilentlyContinue
  if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) {
    return $false
  }
  $environmentPattern = '(?i)(?:[\\/]envs)?[\\/]'+ [regex]::Escape($CondaEnv) + '([\\/]|$)'
  return (
    [string]$process.ExecutablePath -match $environmentPattern -and
    (Test-FusionLiteralContains -Text ([string]$process.CommandLine) -Value $ExpectedCommandMarker) -and
    (Test-FusionLiteralContains -Text ([string]$process.CommandLine) -Value $ExpectedCommandRoot)
  )
}

function Resolve-ServiceListenerPid {
  param(
    [int[]]$Ports,
    [string]$ExpectedIdentity,
    [string]$ExpectedCommandMarker = "",
    [string]$ExpectedCommandRoot = "",
    [string]$CondaEnv = "xiaozhi-env"
  )

  $listenerPid = Resolve-FusionPortOwnerPid -Ports $Ports
  if (-not (Test-FusionProcessIdentity -ProcessId $listenerPid -ExpectedIdentity $ExpectedIdentity -ExpectedCommandMarker $ExpectedCommandMarker -ExpectedCommandRoot $ExpectedCommandRoot -CondaEnv $CondaEnv)) {
    throw "Unknown listener owner: PID $listenerPid does not match the expected service identity."
  }
  return $listenerPid
}

function Stop-FusionOwnedProcess {
  param(
    [int]$ProcessId,
    [string]$ExpectedIdentity,
    [string]$ExpectedCommandMarker = "",
    [string]$ExpectedCommandRoot = "",
    [string]$CondaEnv = "xiaozhi-env",
    [switch]$WhatIf
  )

  if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
    return $false
  }
  if (-not (Test-FusionProcessIdentity -ProcessId $ProcessId -ExpectedIdentity $ExpectedIdentity -ExpectedCommandMarker $ExpectedCommandMarker -ExpectedCommandRoot $ExpectedCommandRoot -CondaEnv $CondaEnv)) {
    throw "Refusing to stop PID $ProcessId because its runtime identity is unknown."
  }
  if (-not $WhatIf) {
    Stop-Process -Id $ProcessId -Force
  }
  return $true
}

function Stop-FusionWrapperProcess {
  param(
    [int]$ProcessId,
    [string]$ExpectedCommandMarker,
    [string]$ExpectedCommandRoot,
    [switch]$WhatIf
  )

  if ($ProcessId -le 0) {
    return $false
  }
  $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction SilentlyContinue
  if ($null -eq $process) {
    return $false
  }
  $commandLine = [string]$process.CommandLine
  if (
    -not (Test-FusionLiteralContains -Text $commandLine -Value "conda") -or
    -not (Test-FusionLiteralContains -Text $commandLine -Value $ExpectedCommandMarker) -or
    -not (Test-FusionLiteralContains -Text $commandLine -Value $ExpectedCommandRoot)
  ) {
    throw "Refusing to stop wrapper PID $ProcessId because its runtime identity is unknown."
  }
  if (-not $WhatIf) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  }
  return $true
}

function Wait-FusionPortsReleased {
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

function Write-FusionJsonAtomic {
  param(
    [string]$Path,
    [object]$Value
  )

  $directory = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $directory | Out-Null
  $temporaryPath = Join-Path $directory (".{0}.{1}.tmp" -f ([System.IO.Path]::GetFileName($Path)), [guid]::NewGuid().ToString("N"))
  try {
    $Value | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryPath -Encoding utf8
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
      [System.IO.File]::Replace($temporaryPath, $Path, $null)
    }
    else {
      [System.IO.File]::Move($temporaryPath, $Path)
    }
  }
  finally {
    if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
      Remove-Item -LiteralPath $temporaryPath -Force
    }
  }
}
