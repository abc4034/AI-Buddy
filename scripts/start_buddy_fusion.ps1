param(
  [string]$AdvertiseHost = "",
  [string]$CondaEnv = "xiaozhi-env",
  [string]$ServerDir = "xiaozhi_server",
  [string]$RuntimeStatePath = ""
)

$ErrorActionPreference = "Stop"

function Get-FusionRepoRoot {
  [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Resolve-FusionPath {
  param([string]$Path)

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path (Get-FusionRepoRoot) $Path))
}

function Get-FusionRuntimeStatePath {
  param([string]$RuntimeStatePath = "")

  if (-not [string]::IsNullOrWhiteSpace($RuntimeStatePath)) {
    return Resolve-FusionPath -Path $RuntimeStatePath
  }
  return Join-Path (Get-FusionRepoRoot) "tmp\runtime\buddy-fusion.json"
}

function Get-FusionProviderEnvironmentNames {
  return @(
    "ASR_PROVIDER", "ASR_HTTP_URL", "ASR_MODEL", "ASR_API_KEY", "ASR_TIMEOUT_SECONDS",
    "TTS_PROVIDER", "TTS_HTTP_URL", "TTS_MODEL", "TTS_API_KEY", "TTS_VOICE", "TTS_LANGUAGE", "TTS_TIMEOUT_SECONDS"
  )
}

function Copy-FusionProviderEnvironmentToProcess {
  foreach ($name in @(Get-FusionProviderEnvironmentNames)) {
    $current = [System.Environment]::GetEnvironmentVariable($name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($current)) {
      continue
    }
    $userValue = [System.Environment]::GetEnvironmentVariable($name, "User")
    if (-not [string]::IsNullOrWhiteSpace($userValue)) {
      [System.Environment]::SetEnvironmentVariable($name, $userValue, "Process")
    }
  }
}

function Invoke-RenderFusionConfig {
  param([string]$AdvertiseHost)

  $renderer = Join-Path $PSScriptRoot "render_xiaozhi_config.ps1"
  $null = & $renderer -HostIp $AdvertiseHost
}

function ConvertTo-FusionArgumentText {
  param([string[]]$ArgumentList)

  return (($ArgumentList | ForEach-Object {
    if ($_ -match '[\s"]') {
      '"' + $_.Replace('"', '\"') + '"'
    }
    else {
      $_
    }
  }) -join " ")
}

function Start-FusionProcess {
  param(
    [string]$Name,
    [string]$WorkingDirectory,
    [string[]]$ArgumentList
  )

  $conda = Get-Command conda -ErrorAction Stop
  $argumentText = ConvertTo-FusionArgumentText -ArgumentList $ArgumentList
  return Start-Process -FilePath $conda.Source -ArgumentList $argumentText -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
}

function Wait-FusionHttpHealth {
  param(
    [int]$Port,
    [int]$TimeoutSeconds = 30
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    try {
      $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
      if ($response.status -eq "ok") {
        return
      }
    }
    catch {
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)

  throw "Service health check did not succeed on port $Port."
}

function Wait-FusionPorts {
  param(
    [int[]]$Ports,
    [int]$TimeoutSeconds = 30
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    $listening = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.LocalPort })
    if (@($Ports | Where-Object { $listening -notcontains $_ }).Count -eq 0) {
      return
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)

  throw "Service listeners did not become ready on ports $($Ports -join ', ')."
}

function Assert-FusionPortsAvailable {
  param([int[]]$Ports)

  $busy = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $Ports -contains [int]$_.LocalPort })
  if ($busy.Count -gt 0) {
    throw "Refusing to start because one or more fusion ports are already owned. Use check_local_demo_status.ps1 to inspect them."
  }
}

function Resolve-ServiceListenerPid {
  param(
    [int[]]$Ports,
    [string]$ExpectedIdentity,
    [string]$CondaEnv
  )

  if (-not [System.IO.Path]::IsPathRooted($ExpectedIdentity)) {
    throw "Expected service identity must be an absolute path."
  }
  $expected = [System.IO.Path]::GetFullPath($ExpectedIdentity)
  $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $Ports -contains [int]$_.LocalPort })
  $pids = @()
  foreach ($port in $Ports) {
    $owner = @($connections | Where-Object { [int]$_.LocalPort -eq $port })
    if ($owner.Count -ne 1 -or -not $owner[0].OwningProcess) {
      throw "Unknown listener owner for required port $port."
    }
    $pids += [int]$owner[0].OwningProcess
  }
  $pids = @($pids | Sort-Object -Unique)
  if ($pids.Count -ne 1) {
    throw "Required ports must have the same listener PID."
  }

  $listenerProcessId = [int]$pids[0]
  $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId = {0}" -f $listenerProcessId) -ErrorAction SilentlyContinue
  if ($null -eq $process -or [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) {
    throw "Unknown listener owner for PID $listenerProcessId."
  }
  $environmentPattern = '(?i)(?:[\\/]envs)?[\\/]'+ [regex]::Escape($CondaEnv) + '([\\/]|$)'
  if ([string]$process.ExecutablePath -notmatch $environmentPattern) {
    throw "Listener PID $listenerProcessId is not running from conda environment '$CondaEnv'."
  }
  if ([string]$process.CommandLine -notlike "*$expected*") {
    throw "Listener PID $listenerProcessId does not contain the expected service identity."
  }
  return $listenerProcessId
}

. (Join-Path $PSScriptRoot "fusion_process_helpers.ps1")

function Write-FusionRuntimeState {
  param(
    [string]$RuntimeStatePath,
    [int]$BuddyListenerPid,
    [int]$BuddyWrapperPid,
    [string]$BuddyIdentity,
    [string]$BuddyCommandMarker,
    [string]$BuddyCommandRoot,
    [int]$XiaoZhiListenerPid,
    [int]$XiaoZhiWrapperPid,
    [string]$XiaoZhiIdentity,
    [string]$XiaoZhiCommandMarker,
    [string]$XiaoZhiCommandRoot
  )

  $state = [pscustomobject]@{
    SchemaVersion = 2
    BuddyCore = [pscustomobject]@{
      ListenerPid = $BuddyListenerPid
      WrapperPid = $BuddyWrapperPid
      ExpectedIdentity = $BuddyIdentity
      ExpectedCommandMarker = $BuddyCommandMarker
      ExpectedCommandRoot = $BuddyCommandRoot
      Ports = @(8010)
    }
    XiaoZhi = [pscustomobject]@{
      ListenerPid = $XiaoZhiListenerPid
      WrapperPid = $XiaoZhiWrapperPid
      ExpectedIdentity = $XiaoZhiIdentity
      ExpectedCommandMarker = $XiaoZhiCommandMarker
      ExpectedCommandRoot = $XiaoZhiCommandRoot
      Ports = @(8000, 8003)
    }
  }
  Write-FusionJsonAtomic -Path $RuntimeStatePath -Value $state
}

function Invoke-StartBuddyFusion {
  param(
    [string]$AdvertiseHost,
    [string]$CondaEnv = "xiaozhi-env",
    [string]$ServerDir = "xiaozhi_server",
    [string]$RuntimeStatePath = ""
  )

  $repoRoot = Get-FusionRepoRoot
  $serverRoot = Resolve-FusionPath -Path $ServerDir
  $xiaozhiApp = Join-Path $serverRoot "app.py"
  $buddyIdentity = Join-Path $repoRoot "buddy_brain\app.py"
  $buddyCommandMarker = "buddy_brain.app:app"
  $buddyCommandRoot = $repoRoot
  $xiaozhiCommandMarker = $xiaozhiApp
  $xiaozhiCommandRoot = $xiaozhiApp
  $statePath = Get-FusionRuntimeStatePath -RuntimeStatePath $RuntimeStatePath
  if (-not (Test-Path -LiteralPath $xiaozhiApp -PathType Leaf)) {
    throw "XiaoZhi app.py was not found under the requested server directory."
  }
  if (-not (Test-Path -LiteralPath $buddyIdentity -PathType Leaf)) {
    throw "Buddy Core app.py was not found."
  }

  Assert-FusionPortsAvailable -Ports @(8010, 8000, 8003)
  Copy-FusionProviderEnvironmentToProcess
  Invoke-RenderFusionConfig -AdvertiseHost $AdvertiseHost

  $buddyWrapper = $null
  $xiaozhiWrapper = $null
  $buddyListener = 0
  $xiaozhiListener = 0
  try {
    $buddyWrapper = Start-FusionProcess -Name "buddy-core" -WorkingDirectory $repoRoot -ArgumentList @(
      "run", "--no-capture-output", "-n", $CondaEnv, "python", "-m", "uvicorn", $buddyCommandMarker, "--app-dir", $repoRoot, "--host", "0.0.0.0", "--port", "8010"
    )
    Wait-FusionPorts -Ports @(8010)
    $buddyListener = Resolve-ServiceListenerPid -Ports @(8010) -ExpectedIdentity $buddyIdentity -ExpectedCommandMarker $buddyCommandMarker -ExpectedCommandRoot $buddyCommandRoot -CondaEnv $CondaEnv
    Wait-FusionHttpHealth -Port 8010

    $xiaozhiWrapper = Start-FusionProcess -Name "xiaozhi" -WorkingDirectory $serverRoot -ArgumentList @(
      "run", "--no-capture-output", "-n", $CondaEnv, "python", $xiaozhiApp
    )
    Wait-FusionPorts -Ports @(8000, 8003)
    $xiaozhiListener = Resolve-ServiceListenerPid -Ports @(8000, 8003) -ExpectedIdentity $xiaozhiApp -ExpectedCommandMarker $xiaozhiCommandMarker -ExpectedCommandRoot $xiaozhiCommandRoot -CondaEnv $CondaEnv
    Wait-FusionHttpHealth -Port 8003

    Write-FusionRuntimeState -RuntimeStatePath $statePath -BuddyListenerPid $buddyListener -BuddyWrapperPid $buddyWrapper.Id -BuddyIdentity $buddyIdentity -BuddyCommandMarker $buddyCommandMarker -BuddyCommandRoot $buddyCommandRoot -XiaoZhiListenerPid $xiaozhiListener -XiaoZhiWrapperPid $xiaozhiWrapper.Id -XiaoZhiIdentity $xiaozhiApp -XiaoZhiCommandMarker $xiaozhiCommandMarker -XiaoZhiCommandRoot $xiaozhiCommandRoot
    return [pscustomobject]@{ RuntimeStatePath = $statePath; BuddyCorePid = $buddyListener; XiaoZhiPid = $xiaozhiListener }
  }
  catch {
    $startupError = $_.Exception.Message
    $cleanupErrors = @()
    foreach ($service in @(
      [pscustomobject]@{ ListenerPid = $xiaozhiListener; Wrapper = $xiaozhiWrapper; Ports = @(8000, 8003); Identity = $xiaozhiApp; Marker = $xiaozhiCommandMarker; Root = $xiaozhiCommandRoot },
      [pscustomobject]@{ ListenerPid = $buddyListener; Wrapper = $buddyWrapper; Ports = @(8010); Identity = $buddyIdentity; Marker = $buddyCommandMarker; Root = $buddyCommandRoot }
    )) {
      try {
        if ([int]$service.ListenerPid -gt 0) {
          [void](Stop-FusionOwnedProcess -ProcessId ([int]$service.ListenerPid) -ExpectedIdentity $service.Identity -ExpectedCommandMarker $service.Marker -ExpectedCommandRoot $service.Root -CondaEnv $CondaEnv)
          Wait-FusionPortsReleased -Ports $service.Ports
        }
        if ($service.Wrapper) {
          [void](Stop-FusionWrapperProcess -ProcessId ([int]$service.Wrapper.Id) -ExpectedCommandMarker $service.Marker -ExpectedCommandRoot $service.Root)
        }
      }
      catch {
        $cleanupErrors += $_.Exception.Message
      }
    }
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
      Remove-Item -LiteralPath $statePath -Force
    }
    $cleanupSuffix = if ($cleanupErrors.Count -gt 0) { " Cleanup errors: $($cleanupErrors -join '; ')" } else { "" }
    throw "Fusion startup failed: $startupError.$cleanupSuffix"
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  if ([string]::IsNullOrWhiteSpace($AdvertiseHost)) {
    throw "AdvertiseHost is required."
  }
  Invoke-StartBuddyFusion -AdvertiseHost $AdvertiseHost -CondaEnv $CondaEnv -ServerDir $ServerDir -RuntimeStatePath $RuntimeStatePath | ConvertTo-Json -Depth 5
}
