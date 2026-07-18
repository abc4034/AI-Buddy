param(
  [string[]]$AllowedTestFixturePath = @()
)

$ErrorActionPreference = "Stop"

function Test-PlaceholderValue {
  param([Parameter(Mandatory = $true)][string]$Value)

  $normalized = $Value.Trim().Trim("'", '"').ToLowerInvariant()
  return $normalized -in @("", "placeholder", "changeme", "example", "your-api-key", "your_api_key", "replace-me", "replace_me", "***") -or
    $normalized.StartsWith('${') -or $normalized.StartsWith("<")
}

function Test-NonPlaceholderKeyAssignment {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)

  $match = [regex]::Match($Line, '(?i)(?:^|\s)(?:export\s+)?[A-Z][A-Z0-9_]*(?:API_KEY|API_TOKEN|ACCESS_TOKEN|AUTH_TOKEN|SECRET|TOKEN|KEY)[A-Z0-9_]*\s*=\s*([^\s#]+)')
  return $match.Success -and -not (Test-PlaceholderValue -Value $match.Groups[1].Value)
}

function Invoke-StagedSecretScan {
  param(
    [string[]]$AllowedTestFixturePath = @()
  )

  if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to scan the staged diff."
  }
  $diff = @(& git diff --cached --no-color)
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the staged diff."
  }

  $allowed = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($path in $AllowedTestFixturePath) {
    if ([string]::IsNullOrWhiteSpace($path) -or [System.IO.Path]::IsPathRooted($path) -or $path -match '(^|[\\/])\.\.([\\/]|$)') {
      throw "Allowed test fixture path is invalid."
    }
    [void]$allowed.Add($path.Replace('\', '/'))
  }

  $currentPath = ""
  foreach ($line in @($diff)) {
    if ($line.StartsWith("+++ b/")) {
      $currentPath = $line.Substring(6).Replace('\', '/')
      continue
    }
    if (-not $line.StartsWith("+") -or $line.StartsWith("+++")) {
      continue
    }

    $added = $line.Substring(1)
    $hasSkToken = $added -match '(?i)\bsk-[a-z0-9_-]{8,}\b'
    $hasBearerToken = $added -match '(?i)\bbearer\s+[a-z0-9._-]{8,}'
    $hasKeyAssignment = Test-NonPlaceholderKeyAssignment -Line $added
    if (($hasSkToken -or $hasBearerToken -or $hasKeyAssignment) -and -not $allowed.Contains($currentPath)) {
      throw ("Potential secret detected in staged path '{0}'." -f $currentPath)
    }
  }

  Write-Output "Staged secret scan passed."
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StagedSecretScan -AllowedTestFixturePath $AllowedTestFixturePath
}
