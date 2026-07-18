param(
    [Parameter(Mandatory = $true)]
    [string]$SourceCheckout,
    [string]$Destination,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ExpectedOrigin = "https://github.com/xinnan-tech/xiaozhi-esp32-server.git"
$ExpectedCommit = "8ec585102711516bf214b262f7d87bc04f9597e2"
$ExpectedTree = "7b96e40bf6541e9b94bdf7c53de9266e3590464d"
$SourceSubtree = "main/xiaozhi-server"

function Get-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$BasePath)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Assert-GitValue {
    param([Parameter(Mandatory = $true)][string]$Actual, [Parameter(Mandatory = $true)][string]$Expected, [Parameter(Mandatory = $true)][string]$Label)

    if ($Actual.Trim() -ne $Expected) {
        throw "Unexpected XiaoZhi ${Label}: $Actual"
    }
}

function Import-XiaoZhiRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$SourceCheckout,
        [Parameter(Mandatory = $true)][string]$Destination,
        [switch]$Force
    )

    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $expectedDestination = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "xiaozhi_server"))
    $destinationPath = Get-AbsolutePath -Path $Destination -BasePath $repoRoot
    if ($destinationPath -ne $expectedDestination) {
        throw "Destination must resolve exactly to $expectedDestination"
    }
    $sourcePath = (Resolve-Path -LiteralPath $SourceCheckout).Path
    $destinationPrefix = $expectedDestination.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    if ($sourcePath -eq $expectedDestination -or $sourcePath.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source checkout must stay outside $expectedDestination"
    }

    $origin = (& git -C $sourcePath remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to read source checkout origin" }
    Assert-GitValue -Actual $origin -Expected $ExpectedOrigin -Label "origin"
    $commit = (& git -C $sourcePath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to read source checkout commit" }
    Assert-GitValue -Actual $commit -Expected $ExpectedCommit -Label "commit"
    $tree = (& git -C $sourcePath rev-parse "HEAD^{tree}").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to read source checkout tree" }
    Assert-GitValue -Actual $tree -Expected $ExpectedTree -Label "tree"
    $status = (& git -C $sourcePath status --porcelain) -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace($status)) {
        throw "Source checkout must be clean"
    }

    $tmpRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "tmp"))
    New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null
    $archivePath = Join-Path $tmpRoot "xiaozhi-esp32-server-$ExpectedCommit.tar"
    $stagePath = Join-Path $tmpRoot "xiaozhi-import-$ExpectedCommit"
    if (Test-Path -LiteralPath $stagePath) {
        Remove-Item -LiteralPath $stagePath -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $stagePath | Out-Null

    try {
        & git -C $sourcePath archive --format=tar --output=$archivePath $ExpectedCommit $SourceSubtree
        if ($LASTEXITCODE -ne 0) { throw "Unable to create pinned XiaoZhi archive" }
        $archiveSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        & tar -xf $archivePath -C $stagePath
        if ($LASTEXITCODE -ne 0) { throw "Unable to extract pinned XiaoZhi archive" }
        $archiveSubtree = Join-Path $stagePath $SourceSubtree
        if (-not (Test-Path -LiteralPath $archiveSubtree -PathType Container)) {
            throw "Archive did not contain $SourceSubtree"
        }
        $sourceRuntime = Join-Path $sourcePath $SourceSubtree
        if (-not (Test-Path -LiteralPath $sourceRuntime -PathType Container)) {
            throw "Source checkout did not contain $SourceSubtree"
        }

        if (Test-Path -LiteralPath $expectedDestination) {
            if (-not $Force) { throw "Destination exists; pass -Force only for $expectedDestination" }
            Remove-Item -LiteralPath $expectedDestination -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $expectedDestination | Out-Null
        Get-ChildItem -LiteralPath $sourceRuntime -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $expectedDestination -Recurse -Force
        }

        $expectedCount = @((& git -C $sourcePath ls-tree -r --name-only $ExpectedCommit -- $SourceSubtree) | Where-Object { $_ }).Count
        $actualCount = @(Get-ChildItem -LiteralPath $expectedDestination -Recurse -File -Force).Count
        if ($expectedCount -ne $actualCount) {
            throw "Imported file count $actualCount does not equal pinned source count $expectedCount"
        }

        $thirdPartyDir = Join-Path $repoRoot "third_party\xiaozhi-esp32-server"
        New-Item -ItemType Directory -Force -Path $thirdPartyDir | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourcePath "LICENSE") -Destination (Join-Path $thirdPartyDir "LICENSE") -Force
        $metadataPath = Join-Path $tmpRoot "xiaozhi-upstream-$ExpectedCommit.json"
        $metadata = [ordered]@{
            origin = $ExpectedOrigin
            commit = $ExpectedCommit
            tree = $ExpectedTree
            archive_sha256 = $archiveSha256
            imported_at = (Get-Date).ToUniversalTime().ToString("o")
            source_subtree = $SourceSubtree
        } | ConvertTo-Json -Depth 3
        [System.IO.File]::WriteAllText($metadataPath, $metadata + "`n", [System.Text.UTF8Encoding]::new($false))

        Push-Location $repoRoot
        try {
            & conda run -n xiaozhi-env python -m integrations.xiaozhi_server.provenance build-manifest `
                --source-dir $sourceRuntime `
                --imported-dir $expectedDestination `
                --metadata-file $metadataPath `
                --upstream-file (Join-Path $thirdPartyDir "UPSTREAM.json") `
                --source-manifest (Join-Path $thirdPartyDir "SOURCE_MANIFEST.json")
            if ($LASTEXITCODE -ne 0) { throw "Unable to generate XiaoZhi provenance manifests" }
        }
        finally {
            Pop-Location
        }
        Write-Host "Imported $actualCount pinned XiaoZhi runtime files."
    }
    finally {
        if (Test-Path -LiteralPath $stagePath) {
            Remove-Item -LiteralPath $stagePath -Recurse -Force
        }
    }
}

if (-not $Destination) {
    $Destination = Join-Path ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))) "xiaozhi_server"
}

if ($MyInvocation.InvocationName -ne ".") {
    Import-XiaoZhiRuntime -SourceCheckout $SourceCheckout -Destination $Destination -Force:$Force
}
