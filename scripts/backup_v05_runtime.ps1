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

function Test-V05PathsOverlap {
  param(
    [Parameter(Mandatory = $true)][string]$First,
    [Parameter(Mandatory = $true)][string]$Second
  )

  $firstPath = [System.IO.Path]::GetFullPath($First).TrimEnd([char[]]@('\', '/'))
  $secondPath = [System.IO.Path]::GetFullPath($Second).TrimEnd([char[]]@('\', '/'))
  $separator = [System.IO.Path]::DirectorySeparatorChar
  return $firstPath.Equals($secondPath, [System.StringComparison]::OrdinalIgnoreCase) -or
    $firstPath.StartsWith($secondPath + $separator, [System.StringComparison]::OrdinalIgnoreCase) -or
    $secondPath.StartsWith($firstPath + $separator, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-V05NoDestinationReparsePoint {
  param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  $rootPath = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd([char[]]@('\', '/'))
  $destinationPath = [System.IO.Path]::GetFullPath($Destination)
  $prefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
  if (-not $destinationPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Restore destination is outside the repository."
  }

  $components = @($rootPath)
  $current = $rootPath
  $relativePath = $destinationPath.Substring($prefix.Length)
  foreach ($segment in $relativePath.Split([char[]]@('\', '/'), [System.StringSplitOptions]::RemoveEmptyEntries)) {
    $current = Join-Path $current $segment
    $components += $current
  }

  foreach ($component in $components) {
    if (-not (Test-Path -LiteralPath $component)) {
      break
    }
    $item = Get-Item -LiteralPath $component -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "Restore destination contains an existing reparse-point component."
    }
  }
}

function Resolve-V05ApprovedBackupRoot {
  param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$BackupRoot
  )

  $repositoryPath = [System.IO.Path]::GetFullPath($RepositoryRoot)
  $approvedRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryPath "tmp/v05-runtime-backup")).TrimEnd([char[]]@('\', '/'))
  $candidate = if ([System.IO.Path]::IsPathRooted($BackupRoot)) {
    [System.IO.Path]::GetFullPath($BackupRoot)
  }
  else {
    [System.IO.Path]::GetFullPath((Join-Path $repositoryPath $BackupRoot))
  }
  $candidate = $candidate.TrimEnd([char[]]@('\', '/'))
  $approvedPrefix = $approvedRoot + [System.IO.Path]::DirectorySeparatorChar
  if (-not $candidate.Equals($approvedRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
      -not $candidate.StartsWith($approvedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup root must be within the approved ignored runtime backup tree."
  }

  $sourcePaths = @(
    (Join-Path $repositoryPath ".env"),
    (Join-Path $repositoryPath $script:XiaoZhiConfigRelativePath),
    (Join-Path $repositoryPath $script:GatewayAudioRelativeRoot)
  )
  foreach ($sourcePath in $sourcePaths) {
    if (Test-V05PathsOverlap -First $candidate -Second $sourcePath) {
      throw "Backup root overlaps a runtime source path."
    }
  }
  Assert-V05NoDestinationReparsePoint -RepositoryRoot $repositoryPath -Destination $candidate
  $candidate
}

function Assert-V05RegularFileDestination {
  param([Parameter(Mandatory = $true)][string]$Destination)

  if (Test-Path -LiteralPath $Destination) {
    $item = Get-Item -LiteralPath $Destination -Force
    if ($item -isnot [System.IO.FileInfo]) {
      throw "Existing restore destination is not a regular file."
    }
  }
}

function Write-V05Utf8Json {
  param(
    [Parameter(Mandatory = $true)][object]$Value,
    [Parameter(Mandatory = $true)][string]$Path
  )

  $json = $Value | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Read-V05JsonFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$InvalidMessage
  )

  try {
    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -ErrorAction Stop
  }
  catch {
    throw $InvalidMessage
  }
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

function Set-V05EnvironmentVariable {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [AllowNull()][string]$Value,
    [Parameter(Mandatory = $true)][ValidateSet("Process", "User")][string]$EnvironmentTarget
  )

  [System.Environment]::SetEnvironmentVariable($Name, $Value, $EnvironmentTarget)
}

function Set-V05EnvironmentFromSnapshot {
  param(
    [Parameter(Mandatory = $true)][object]$Snapshot,
    [Parameter(Mandatory = $true)][ValidateSet("Process", "User")][string]$EnvironmentTarget
  )

  foreach ($name in $script:EnvironmentNames) {
    $value = $null
    if ($Snapshot -is [System.Collections.IDictionary]) {
      if ($Snapshot.Contains($name)) {
        $value = [string]$Snapshot[$name]
      }
    }
    else {
      $property = $Snapshot.psobject.Properties[$name]
      if ($null -ne $property) {
        $value = [string]$property.Value
      }
    }
    Set-V05EnvironmentVariable -Name $name -Value $value -EnvironmentTarget $EnvironmentTarget
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
  $backupRootPath = Resolve-V05ApprovedBackupRoot -RepositoryRoot $repositoryRoot -BackupRoot $BackupRoot
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

  $destination = $null
  if ($RelativePath -eq ".env" -or $RelativePath -eq $script:XiaoZhiConfigRelativePath) {
    $destination = Resolve-V05ChildPath -Root $RepositoryRoot -RelativePath $RelativePath
  }
  else {
    $audioPrefix = $script:GatewayAudioRelativeRoot + "/"
    if ($RelativePath.StartsWith($audioPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
      $destination = Resolve-V05ChildPath -Root $RepositoryRoot -RelativePath $RelativePath
    }
  }
  if ($RelativePath -eq "environment.json") {
    return $null
  }
  if ($null -ne $destination) {
    Assert-V05NoDestinationReparsePoint -RepositoryRoot $RepositoryRoot -Destination $destination
    Assert-V05RegularFileDestination -Destination $destination
    return $destination
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
  $manifest = Read-V05JsonFile -Path $manifestPath -InvalidMessage "Backup manifest is not valid JSON."
  if ([string]$manifest.source_commit -ne $script:V05SourceCommit) {
    throw "Backup manifest source commit does not identify the v0.5 baseline."
  }
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

  $environment = Read-V05JsonFile -Path $environmentPath -InvalidMessage "Backup environment data is not valid JSON."
  foreach ($scope in @("process", "user")) {
    if ($null -eq $environment.$scope) {
      throw "Backup environment data is incomplete."
    }
    foreach ($property in @($environment.$scope.psobject.Properties)) {
      if ($script:EnvironmentNames -notcontains $property.Name -or $property.Value -isnot [string]) {
        throw "Backup environment data is invalid."
      }
      if ($property.Value.Length -eq 0) {
        throw "Backup environment data contains an empty environment value."
      }
    }
  }

  [pscustomobject]@{ FileActions = $fileActions; Environment = $environment }
}

function New-V05PreRestoreSnapshot {
  param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$FileActions,
    [Parameter(Mandatory = $true)][ValidateSet("Process", "User")][string]$EnvironmentTarget
  )

  $snapshot = Join-Path $BackupDir ("pre-restore-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
  New-Item -ItemType Directory -Force -Path $snapshot | Out-Null
  $fileStates = @()
  foreach ($action in $FileActions) {
    $originalExists = Test-Path -LiteralPath $action.Destination -PathType Leaf
    $snapshotPath = $null
    if ($originalExists) {
      $snapshotPath = Resolve-V05ChildPath -Root $snapshot -RelativePath $action.RelativePath
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $snapshotPath) | Out-Null
      Copy-Item -LiteralPath $action.Destination -Destination $snapshotPath -Force
    }
    $fileStates += [pscustomobject]@{
      RelativePath = $action.RelativePath
      Destination = $action.Destination
      OriginalExists = $originalExists
      SnapshotPath = $snapshotPath
    }
  }
  $environment = Get-V05EnvironmentSnapshot
  Write-V05Utf8Json -Value $environment -Path (Join-Path $snapshot "environment.json")

  [pscustomobject]@{
    Directory = $snapshot
    FileStates = $fileStates
    Environment = $environment
  }
}

function Restore-V05FileState {
  param(
    [Parameter(Mandatory = $true)][object]$State,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
  )

  Assert-V05NoDestinationReparsePoint -RepositoryRoot $RepositoryRoot -Destination $State.Destination
  if (-not $State.OriginalExists) {
    if (Test-Path -LiteralPath $State.Destination -PathType Leaf) {
      Remove-Item -LiteralPath $State.Destination -Force
    }
    return
  }
  if ([string]::IsNullOrWhiteSpace([string]$State.SnapshotPath) -or -not (Test-Path -LiteralPath $State.SnapshotPath -PathType Leaf)) {
    throw "Pre-restore snapshot file is missing."
  }

  $parent = Split-Path -Parent $State.Destination
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $temporary = Join-Path $parent ("." + [System.IO.Path]::GetFileName($State.Destination) + ".v05-recovery-" + [guid]::NewGuid().ToString("N") + ".tmp")
  try {
    Assert-V05NoDestinationReparsePoint -RepositoryRoot $RepositoryRoot -Destination $State.Destination
    Assert-V05RegularFileDestination -Destination $State.Destination
    Copy-Item -LiteralPath $State.SnapshotPath -Destination $temporary -Force
    Assert-V05NoDestinationReparsePoint -RepositoryRoot $RepositoryRoot -Destination $State.Destination
    Assert-V05RegularFileDestination -Destination $State.Destination
    Move-Item -LiteralPath $temporary -Destination $State.Destination -Force
  }
  finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
      Remove-Item -LiteralPath $temporary -Force
    }
  }
}

function Invoke-V05BeforeRestoreWrite {
  param([Parameter(Mandatory = $true)][object]$Plan)
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
  $repositoryRoot = Get-V05RepositoryRoot
  $plan = Get-V05ManifestRestorePlan -BackupDir $backupPath -RepositoryRoot $repositoryRoot
  $environmentValues = $plan.Environment.($EnvironmentTarget.ToLowerInvariant())

  if (-not $Apply) {
    foreach ($action in $plan.FileActions) {
      Write-Output ("Validated file restore: {0}" -f $action.RelativePath)
    }
    foreach ($name in $script:EnvironmentNames) {
      Write-Output ("Validated {0} environment restore: {1}" -f $EnvironmentTarget, $name)
    }
    return [pscustomobject]@{ Applied = $false; FileCount = @($plan.FileActions).Count; EnvironmentTarget = $EnvironmentTarget }
  }

  $snapshot = New-V05PreRestoreSnapshot -BackupDir $backupPath -FileActions @($plan.FileActions) -EnvironmentTarget $EnvironmentTarget
  $statesByPath = @{}
  foreach ($state in $snapshot.FileStates) {
    $statesByPath[$state.RelativePath] = $state
  }
  $temporaryFiles = @()
  $appliedStates = @()
  try {
    Invoke-V05BeforeRestoreWrite -Plan $plan
    foreach ($action in $plan.FileActions) {
      $parent = Split-Path -Parent $action.Destination
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
      $temporary = Join-Path $parent ("." + [System.IO.Path]::GetFileName($action.Destination) + ".v05-restore-" + [guid]::NewGuid().ToString("N") + ".tmp")
      Assert-V05NoDestinationReparsePoint -RepositoryRoot $repositoryRoot -Destination $action.Destination
      Assert-V05RegularFileDestination -Destination $action.Destination
      Copy-Item -LiteralPath $action.Source -Destination $temporary -Force
      $temporaryFiles += [pscustomobject]@{
        Temporary = $temporary
        Destination = $action.Destination
        State = $statesByPath[$action.RelativePath]
      }
    }

    foreach ($temporaryFile in $temporaryFiles) {
      Assert-V05NoDestinationReparsePoint -RepositoryRoot $repositoryRoot -Destination $temporaryFile.Destination
      Assert-V05RegularFileDestination -Destination $temporaryFile.Destination
      Move-Item -LiteralPath $temporaryFile.Temporary -Destination $temporaryFile.Destination -Force
      $appliedStates += $temporaryFile.State
    }
    Set-V05EnvironmentFromSnapshot -Snapshot $environmentValues -EnvironmentTarget $EnvironmentTarget
  }
  catch {
    $recoveryFailureCount = 0
    for ($index = $appliedStates.Count - 1; $index -ge 0; $index--) {
      try {
        Restore-V05FileState -State $appliedStates[$index] -RepositoryRoot $repositoryRoot
      }
      catch {
        $recoveryFailureCount += 1
      }
    }
    try {
      $originalEnvironment = $snapshot.Environment.($EnvironmentTarget.ToLowerInvariant())
      Set-V05EnvironmentFromSnapshot -Snapshot $originalEnvironment -EnvironmentTarget $EnvironmentTarget
    }
    catch {
      $recoveryFailureCount += 1
    }

    if ($recoveryFailureCount -gt 0) {
      throw ("Restore failed and deterministic recovery failed for {0} action(s). Pre-restore snapshot: {1}" -f $recoveryFailureCount, $snapshot.Directory)
    }
    throw ("Restore failed; the pre-restore state was recovered. Snapshot: {0}" -f $snapshot.Directory)
  }
  finally {
    foreach ($temporaryFile in $temporaryFiles) {
      if (Test-Path -LiteralPath $temporaryFile.Temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryFile.Temporary -Force
      }
    }
  }

  [pscustomobject]@{ Applied = $true; FileCount = @($plan.FileActions).Count; EnvironmentTarget = $EnvironmentTarget; PreRestoreSnapshot = $snapshot.Directory }
}

if ($MyInvocation.InvocationName -ne ".") {
  New-V05RuntimeBackup -BackupRoot $BackupRoot
}
