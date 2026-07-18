param(
  [string[]]$AllowedTestFixturePath = @()
)

$ErrorActionPreference = "Stop"
$script:ApprovedFixturePathPattern = '^tests/fixtures/secret-scan/[a-z0-9][a-z0-9_.-]*\.fixture$'
$script:ApprovedFixtureMarkerPattern = '(?i)^sk-' + 'test-[a-z0-9_-]+$'

function Test-PlaceholderValue {
  param([Parameter(Mandatory = $true)][string]$Value)

  $normalized = $Value.Trim().Trim(',', '}').Trim().Trim("'", '"').ToLowerInvariant()
  return $normalized -in @("", "placeholder", "changeme", "example", "your-api-key", "your_api_key", "replace-me", "replace_me", "***") -or
    $normalized.StartsWith('${') -or $normalized.StartsWith("<")
}

function Get-SensitiveAssignmentValues {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)

  $sensitiveNamePattern = '(?:API_' + 'KEY|API_' + 'TOKEN|ACCESS_' + 'TOKEN|AUTH_' + 'TOKEN|SECRET|TOKEN|KEY)'
  $sensitiveKeyPattern = '[A-Z][A-Z0-9_.-]*' + $sensitiveNamePattern + '[A-Z0-9_.-]*'
  $patterns = @(
    ('(?i)(?:^|[\s{,;])(?:\$env:)?[''"]?' + $sensitiveKeyPattern + '[''"]?\s*(?:=|:)\s*("[^"]*"|''[^'']*''|[^\s,;#}]+)'),
    ('(?i)(?:^|[\s(,;])(?:os\.)?environ\s*\[\s*[''"]' + $sensitiveKeyPattern + '[''"]\s*\]\s*=\s*("[^"]*"|''[^'']*''|[^\s,;#}]+)')
  )
  $values = @()
  foreach ($pattern in $patterns) {
    foreach ($match in [regex]::Matches($Line, $pattern)) {
      $values += $match.Groups[1].Value
    }
  }
  return $values
}

function Test-NonPlaceholderKeyAssignment {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)

  foreach ($value in @(Get-SensitiveAssignmentValues -Line $Line)) {
    if (-not (Test-PlaceholderValue -Value $value)) {
      return $true
    }
  }
  return $false
}

function Test-ApprovedFixtureLine {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)

  $markers = [regex]::Matches($Line, '(?i)\bsk-[a-z0-9_-]+\b')
  if ($markers.Count -eq 0) {
    return $false
  }
  foreach ($marker in $markers) {
    if ($marker.Value -notmatch $script:ApprovedFixtureMarkerPattern) {
      return $false
    }
  }
  if ($Line -match '(?i)\bbearer\s+[a-z0-9._-]+') {
    return $false
  }

  foreach ($assignmentValue in @(Get-SensitiveAssignmentValues -Line $Line)) {
    $normalized = $assignmentValue.Trim().Trim(',', '}').Trim().Trim("'", '"')
    if ($normalized -notmatch $script:ApprovedFixtureMarkerPattern) {
      return $false
    }
  }
  return $true
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
    $normalizedPath = $path.Replace('\', '/')
    if ($normalizedPath -notmatch $script:ApprovedFixturePathPattern) {
      throw "Allowed test fixture path is not approved."
    }
    [void]$allowed.Add($normalizedPath)
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
    $hasSkToken = $added -match '(?i)\bsk-[a-z0-9_-]+\b'
    $hasBearerToken = $added -match '(?i)\bbearer\s+[a-z0-9._-]+'
    $hasKeyAssignment = Test-NonPlaceholderKeyAssignment -Line $added
    $isApprovedFixture = $allowed.Contains($currentPath) -and (Test-ApprovedFixtureLine -Line $added)
    if (($hasSkToken -or $hasBearerToken -or $hasKeyAssignment) -and -not $isApprovedFixture) {
      throw ("Potential secret detected in staged path '{0}'." -f $currentPath)
    }
  }

  Write-Output "Staged secret scan passed."
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-StagedSecretScan -AllowedTestFixturePath $AllowedTestFixturePath
}
