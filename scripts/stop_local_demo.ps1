param(
  [int[]]$Ports = @(8000, 8003, 8010),
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Get-LocalDemoListenerProcesses {
  param(
    [int[]]$Ports = @(8000, 8003, 8010)
  )

  $connections = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $Ports -contains [int]$_.LocalPort }

  $connections |
    Group-Object OwningProcess |
    ForEach-Object {
      [pscustomobject]@{
        ProcessId = [int]$_.Name
        Ports = @($_.Group | ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique)
      }
    }
}

function Invoke-StopLocalDemo {
  param(
    [int[]]$Ports = @(8000, 8003, 8010),
    [switch]$WhatIf
  )

  $processes = Get-LocalDemoListenerProcesses -Ports $Ports
  if (-not $processes) {
    Write-Host "No local demo listener processes found on ports $($Ports -join ', ')."
    return
  }

  foreach ($entry in $processes) {
    $process = Get-Process -Id $entry.ProcessId -ErrorAction SilentlyContinue
    $name = if ($process) { $process.ProcessName } else { "unknown" }
    Write-Host "Stopping PID $($entry.ProcessId) ($name) for demo ports $($entry.Ports -join ', ')"
    if (-not $WhatIf) {
      Stop-Process -Id $entry.ProcessId -Force
    }
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StopLocalDemo -Ports $Ports -WhatIf:$WhatIf
}
