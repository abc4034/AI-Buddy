param(
  [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"

$script:V05SourceCommit = "22e4712814dfb19f1ecea9bd0e6bfbd24c057ac5"
$script:EnvironmentNames = @(
  "ASR_PROVIDER", "ASR_HTTP_URL", "ASR_MODEL", "ASR_API_KEY", "ASR_TIMEOUT_SECONDS",
  "TTS_PROVIDER", "TTS_HTTP_URL", "TTS_MODEL", "TTS_API_KEY",
  "TTS_VOICE", "TTS_LANGUAGE", "TTS_TIMEOUT_SECONDS"
)
$script:XiaoZhiConfigRelativePath = ".run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml"
$script:GatewayAudioRelativeRoot = "data/gateway_audio"

function Get-V05RepositoryRoot {
  [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function ConvertTo-V05RelativePath {
  param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$Path
  )

  $root = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd([char[]]@('\', '/'))
  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
  if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path is outside the repository."
  }

  $fullPath.Substring($prefix.Length).Replace('\', '/')
}

function Resolve-V05ChildPath {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  if ([System.IO.Path]::IsPathRooted($RelativePath) -or $RelativePath -match "(^|[\\/])\.\.([\\/]|$)") {
    throw "Backup path traversal is not allowed."
  }

  $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\', '/'))
  $candidate = [System.IO.Path]::GetFullPath((Join-Path $rootPath $RelativePath))
  $prefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
  if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved path is outside the approved root."
  }

  $candidate
}

function Write-V05Utf8Json {
  param(
    [Parameter(Mandatory = $true)][object]$Value,
    [Parameter(Mandatory = $true)][string]$Path
  )

  $json = $Value | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Get-V05EnvironmentSnapshot {
  $process = [ordered]@{}
  $user = [ordered]@{}
  foreach ($name in $script:EnvironmentNames) {
    $processValue = [System.Environment]::GetEnvironmentVariable($name, "Process")
    if ($null -ne $processValue) {
      $process[$name] = $processValue
    }

    $userValue = [System.Environment]::GetEnvironmentVariable($name, "User")
    if ($null -ne $userValue) {
      $user[$name] = $userValue
    }
  }

  [ordered]@{
    process = $process
    user = $user
  }
}

function Get-V05FileEntry {
  param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  $path = Resolve-V05ChildPath -Root $BackupDir -RelativePath $RelativePath
  [ordered]@{
    relative_path = $RelativePath
    sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}

function Copy-V05RuntimeFile {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  $destination = Resolve-V05ChildPath -Root $BackupDir -RelativePath $RelativePath
  $destinationParent = Split-Path -Parent $destination
  New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
  Copy-Item -LiteralPath $Source -Destination $destination -Force
}

function New-V05RuntimeBackup {
  param(
    [string]$BackupRoot = ""
  )

  $repositoryRoot = Get-V05RepositoryRoot
  if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Join-Path $repositoryRoot "tmp/v05-runtime-backup"
  }
  $backupRootPath = [System.IO.Path]::GetFullPath($BackupRoot)
  $backupDir = Join-Path $backupRootPath ((Get-Date -Format "yyyyMMdd-HHmmssfff") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
  New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

  $files = @()
  $sources = @(
    [pscustomobject]@{ Path = (Join-Path $repositoryRoot ".env"); RelativePath = ".env" },
    [pscustomobject]@{ Path = (Join-Path $repositoryRoot $script:XiaoZhiConfigRelativePath); RelativePath = $script:XiaoZhiConfigRelativePath }
  )
  foreach ($source in $sources) {
    if (Test-Path -LiteralPath $source.Path -PathType Leaf) {
      Copy-V05RuntimeFile -Source $source.Path -BackupDir $backupDir -RelativePath $source.RelativePath
      $files += Get-V05FileEntry -BackupDir $backupDir -RelativePath $source.RelativePath
    }
  }

  $audioRoot = Join-Path $repositoryRoot $script:GatewayAudioRelativeRoot
  if (Test-Path -LiteralPath $audioRoot -PathType Container) {
    foreach ($audioFile in Get-ChildItem -LiteralPath $audioRoot -File -Recurse) {
      $relativePath = ConvertTo-V05RelativePath -RepositoryRoot $repositoryRoot -Path $audioFile.FullName
      Copy-V05RuntimeFile -Source $audioFile.FullName -BackupDir $backupDir -RelativePath $relativePath
      $files += Get-V05FileEntry -BackupDir $backupDir -RelativePath $relativePath
    }
  }

  $environmentFile = "environment.json"
  $environmentPath = Resolve-V05ChildPath -Root $backupDir -RelativePath $environmentFile
  Write-V05Utf8Json -Value (Get-V05EnvironmentSnapshot) -Path $environmentPath
  $files += Get-V05FileEntry -BackupDir $backupDir -RelativePath $environmentFile

  $manifestPath = Join-Path $backupDir "manifest.json"
  $manifest = [ordered]@{
    source_commit = $script:V05SourceCommit
    files = @($files)
    environment_file = $environmentFile
  }
  Write-V05Utf8Json -Value $manifest -Path $manifestPath

  [pscustomobject]@{
    BackupDir = $backupDir
    ManifestPath = $manifestPath
    ManifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}

function Resolve-V05RestoreDestination {
  param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  if ($RelativePath -eq ".env" -or $RelativePath -eq $script:XiaoZhiConfigRelativePath) {
    return Resolve-V05ChildPath -Root $RepositoryRoot -RelativePath $RelativePath
  }
  $audioPrefix = $script:GatewayAudioRelativeRoot + "/"
  if ($RelativePath.StartsWith($audioPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    return Resolve-V05ChildPath -Root $RepositoryRoot -RelativePath $RelativePath
  }
  if ($RelativePath -eq "environment.json") {
    return $null
  }

  throw "Backup file destination is not approved."
}

function Get-V05ManifestRestorePlan {
  param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
  )

  $manifestPath = Join-Path $BackupDir "manifest.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Backup manifest is missing."
  }
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  if ($null -eq $manifest.files -or [string]::IsNullOrWhiteSpace($manifest.environment_file)) {
    throw "Backup manifest is incomplete."
  }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  $fileActions = @()
  $environmentPath = $null
  foreach ($entry in @($manifest.files)) {
    $relativePath = [string]$entry.relative_path
    $expectedHash = [string]$entry.sha256
    if ([string]::IsNullOrWhiteSpace($relativePath) -or $expectedHash -notmatch "^[0-9a-f]{64}$") {
      throw "Backup manifest contains an invalid file entry."
    }
    if (-not $seen.Add($relativePath)) {
      throw "Backup manifest contains duplicate paths."
    }

    $source = Resolve-V05ChildPath -Root $BackupDir -RelativePath $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
      throw "Backup file is missing."
    }
    $actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
      throw "Backup file hash verification failed."
    }

    $destination = Resolve-V05RestoreDestination -RepositoryRoot $RepositoryRoot -RelativePath $relativePath
    if ($relativePath -eq [string]$manifest.environment_file) {
      $environmentPath = $source
    }
    elseif ($null -ne $destination) {
      $fileActions += [pscustomobject]@{ Source = $source; Destination = $destination; RelativePath = $relativePath }
    }
  }

  if ($null -eq $environmentPath -or [string]$manifest.environment_file -ne "environment.json") {
    throw "Backup environment file is missing or invalid."
  }

  $environment = Get-Content -LiteralPath $environmentPath -Raw | ConvertFrom-Json
  foreach ($scope in @("process", "user")) {
    if ($null -eq $environment.$scope) {
      throw "Backup environment data is incomplete."
    }
    foreach ($property in @($environment.$scope.psobject.Properties)) {
      if ($script:EnvironmentNames -notcontains $property.Name -or $property.Value -isnot [string]) {
        throw "Backup environment data is invalid."
      }
    }
  }

  [pscustomobject]@{ FileActions = $fileActions; Environment = $environment }
}

function New-V05PreRestoreSnapshot {
  param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][object[]]$FileActions,
    [Parameter(Mandatory = $true)][ValidateSet("Process", "User")][string]$EnvironmentTarget
  )

  $snapshot = Join-Path $BackupDir ("pre-restore-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
  New-Item -ItemType Directory -Force -Path $snapshot | Out-Null
  foreach ($action in $FileActions) {
    if (Test-Path -LiteralPath $action.Destination -PathType Leaf) {
      $snapshotPath = Resolve-V05ChildPath -Root $snapshot -RelativePath $action.RelativePath
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $snapshotPath) | Out-Null
      Copy-Item -LiteralPath $action.Destination -Destination $snapshotPath -Force
    }
  }
  Write-V05Utf8Json -Value (Get-V05EnvironmentSnapshot) -Path (Join-Path $snapshot "environment.json")
  $snapshot
}

function Restore-V05RuntimeBackup {
  param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [switch]$Apply,
    [ValidateSet("Process", "User")][string]$EnvironmentTarget = "Process"
  )

  $backupPath = [System.IO.Path]::GetFullPath($BackupDir)
  if (-not (Test-Path -LiteralPath $backupPath -PathType Container)) {
    throw "Backup directory is missing."
  }
  $plan = Get-V05ManifestRestorePlan -BackupDir $backupPath -RepositoryRoot (Get-V05RepositoryRoot)
  $environmentValues = $plan.Environment.($EnvironmentTarget.ToLowerInvariant())

  if (-not $Apply) {
    foreach ($action in $plan.FileActions) {
      Write-Output ("Validated file restore: {0}" -f $action.RelativePath)
    }
    foreach ($property in @($environmentValues.psobject.Properties)) {
      Write-Output ("Validated {0} environment restore: {1}" -f $EnvironmentTarget, $property.Name)
    }
    return [pscustomobject]@{ Applied = $false; FileCount = @($plan.FileActions).Count; EnvironmentTarget = $EnvironmentTarget }
  }

  $snapshot = New-V05PreRestoreSnapshot -BackupDir $backupPath -FileActions @($plan.FileActions) -EnvironmentTarget $EnvironmentTarget
  $temporaryFiles = @()
  try {
    foreach ($action in $plan.FileActions) {
      $parent = Split-Path -Parent $action.Destination
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
      $temporary = Join-Path $parent ("." + [System.IO.Path]::GetFileName($action.Destination) + ".v05-restore-" + [guid]::NewGuid().ToString("N") + ".tmp")
      Copy-Item -LiteralPath $action.Source -Destination $temporary -Force
      $temporaryFiles += [pscustomobject]@{ Temporary = $temporary; Destination = $action.Destination }
    }

    foreach ($temporaryFile in $temporaryFiles) {
      if (Test-Path -LiteralPath $temporaryFile.Destination -PathType Leaf) {
        Move-Item -LiteralPath $temporaryFile.Temporary -Destination $temporaryFile.Destination -Force
      }
      else {
        Move-Item -LiteralPath $temporaryFile.Temporary -Destination $temporaryFile.Destination -Force
      }
    }
    foreach ($property in @($environmentValues.psobject.Properties)) {
      [System.Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, $EnvironmentTarget)
    }
  }
  finally {
    foreach ($temporaryFile in $temporaryFiles) {
      if (Test-Path -LiteralPath $temporaryFile.Temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryFile.Temporary -Force
      }
    }
  }

  [pscustomobject]@{ Applied = $true; FileCount = @($plan.FileActions).Count; EnvironmentTarget = $EnvironmentTarget; PreRestoreSnapshot = $snapshot }
}

if ($MyInvocation.InvocationName -ne ".") {
  New-V05RuntimeBackup -BackupRoot $BackupRoot
}
