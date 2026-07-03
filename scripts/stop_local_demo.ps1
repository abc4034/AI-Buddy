param(
  [string[]]$Ports = @("8000", "8003", "8010"),
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function ConvertTo-PortList {
  param(
    [object[]]$Ports = @("8000", "8003", "8010")
  )

  $portList = @()
  foreach ($port in @($Ports)) {
    foreach ($part in ([string]$port -split ",")) {
      $trimmed = $part.Trim()
      if ([string]::IsNullOrWhiteSpace($trimmed)) {
        continue
      }
      $portList += [int]$trimmed
    }
  }

  return @($portList | Sort-Object -Unique)
}

function Get-LocalDemoListenerProcesses {
  param(
    [object[]]$Ports = @("8000", "8003", "8010")
  )

  $portList = ConvertTo-PortList -Ports $Ports
  $connections = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $portList -contains [int]$_.LocalPort }

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
    [object[]]$Ports = @("8000", "8003", "8010"),
    [switch]$WhatIf
  )

  $portList = ConvertTo-PortList -Ports $Ports
  $processes = Get-LocalDemoListenerProcesses -Ports $portList
  if (-not $processes) {
    Write-Host "No local demo listener processes found on ports $($portList -join ', ')."
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
