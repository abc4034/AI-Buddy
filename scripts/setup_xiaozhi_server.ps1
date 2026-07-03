param(
  [string]$Destination = ".run\xiaozhi-esp32-server",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Resolve-RepoPath {
  param(
    [string]$Path,
    [string]$RepoRoot = (Get-RepoRoot)
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }

  return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Test-IsStrictChildOfDirectory {
  param(
    [string]$Path,
    [string]$ParentDirectory
  )

  $normalizedParent = [System.IO.Path]::GetFullPath($ParentDirectory).TrimEnd("\")
  $normalizedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\")

  if ($normalizedPath.Equals($normalizedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $false
  }

  return $normalizedPath.StartsWith("$normalizedParent\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-XiaoZhiSetupPaths {
  param([string]$Destination)

  $repoRoot = Get-RepoRoot
  $runRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".run"))
  $destinationPath = Resolve-RepoPath -Path $Destination -RepoRoot $repoRoot

  if (-not (Test-IsStrictChildOfDirectory -Path $destinationPath -ParentDirectory $runRoot)) {
    throw "Destination must resolve to a strict child path under $runRoot"
  }

  $runDir = Split-Path -Parent $destinationPath
  $zipPath = [System.IO.Path]::GetFullPath((Join-Path $runDir "xiaozhi-esp32-server-main.zip"))
  $extractDir = [System.IO.Path]::GetFullPath((Join-Path $runDir "xiaozhi-esp32-server-main"))

  if (-not (Test-IsStrictChildOfDirectory -Path $zipPath -ParentDirectory $runRoot)) {
    throw "Zip path must stay under $runRoot"
  }

  if (-not (Test-IsStrictChildOfDirectory -Path $extractDir -ParentDirectory $runRoot)) {
    throw "Extract path must stay under $runRoot"
  }

  return [pscustomobject]@{
    RepoRoot = $repoRoot
    RunRoot = $runRoot
    DestinationPath = $destinationPath
    RunDir = $runDir
    ZipUrl = "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/heads/main.zip"
    ZipPath = $zipPath
    ExtractDir = $extractDir
  }
}

function Update-XiaoZhiOpenAIProviderPatch {
  param([string]$ProviderPath)

  if (-not (Test-Path -LiteralPath $ProviderPath)) {
    throw "OpenAI provider not found at $ProviderPath"
  }

  $text = Get-Content -Raw -Encoding UTF8 -LiteralPath $ProviderPath

  if ($text -notmatch "forward_device_metadata") {
    $text = $text.Replace(
      '        self.api_key = config.get("api_key")',
      "        self.api_key = config.get(`"api_key`")`r`n        self.forward_device_metadata = _as_bool(config.get(`"forward_device_metadata`", False))"
    )
  }

  if ($text -notmatch "def _apply_device_metadata") {
    $helper = @'
    def _apply_device_metadata(self, request_params: dict, session_id, kwargs: dict):
        if not self.forward_device_metadata:
            return
        metadata = {"session_id": session_id}
        device_id = kwargs.get("device_id")
        client_id = kwargs.get("client_id")
        if device_id:
            metadata["device_id"] = device_id
        if client_id:
            metadata["client_id"] = client_id
        request_params.setdefault("extra_body", {}).setdefault("metadata", {}).update(metadata)

'@
    $text = $text.Replace("    def response(self, session_id, dialogue, **kwargs):", $helper + "    def response(self, session_id, dialogue, **kwargs):")
  }

  if ($text -notmatch "_apply_device_metadata\(request_params, session_id, kwargs\)") {
    $text = $text.Replace(
      "        self._apply_thinking_disabled(request_params)",
      "        self._apply_thinking_disabled(request_params)`r`n        self._apply_device_metadata(request_params, session_id, kwargs)"
    )
  }

  if ($text -notmatch "def _as_bool") {
    $text = $text.TrimEnd() + @'


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)
'@
  }

  Set-Content -LiteralPath $ProviderPath -Encoding UTF8 -NoNewline -Value $text
}

function Update-XiaoZhiConnectionPatch {
  param([string]$ConnectionPath)

  if (-not (Test-Path -LiteralPath $ConnectionPath)) {
    throw "Connection handler not found at $ConnectionPath"
  }

  $text = Get-Content -Raw -Encoding UTF8 -LiteralPath $ConnectionPath

  if ($text -notmatch "llm_kwargs = \{\}") {
    $block = @'
        response_message = []
        llm_kwargs = {}
        if getattr(self.llm, "forward_device_metadata", False):
            llm_kwargs = {
                "device_id": self.device_id,
                "client_id": self.headers.get("client-id", self.device_id),
            }
'@
    $text = $text.Replace("        response_message = []", $block)
  }

  if ($text -notmatch "\*\*llm_kwargs") {
    $lines = $text -split "\r?\n"
    $patched = [System.Collections.Generic.List[string]]::new()
    $insideNormalResponse = $false

    foreach ($line in $lines) {
      $patched.Add($line)

      if ($line -match "self\.llm\.response\(" -and $line -notmatch "response_with_functions") {
        $insideNormalResponse = $true
        continue
      }

      if ($line -match "^(\s*)functions=functions,") {
        $patched.Add("$($Matches[1])**llm_kwargs,")
        continue
      }

      if ($insideNormalResponse -and $line.Trim().EndsWith("),")) {
        $indent = $line.Substring(0, $line.Length - $line.TrimStart().Length)
        $patched.Add("${indent}**llm_kwargs,")
        $insideNormalResponse = $false
      }
    }

    $text = $patched -join "`r`n"
  }

  Set-Content -LiteralPath $ConnectionPath -Encoding UTF8 -NoNewline -Value $text
}

function Update-XiaoZhiDeviceMetadataPatch {
  param([string]$ServerDir)

  $providerPath = Join-Path $ServerDir "core\providers\llm\openai\openai.py"
  $connectionPath = Join-Path $ServerDir "core\connection.py"
  Update-XiaoZhiOpenAIProviderPatch -ProviderPath $providerPath
  Update-XiaoZhiConnectionPatch -ConnectionPath $connectionPath
}

function Invoke-XiaoZhiSetup {
  param(
    [string]$Destination,
    [switch]$Force
  )

  $paths = Get-XiaoZhiSetupPaths -Destination $Destination

  if ((Test-Path -LiteralPath $paths.DestinationPath) -and -not $Force) {
    Write-Host "XiaoZhi server already exists at $($paths.DestinationPath)"
    return
  }

  if (Test-Path -LiteralPath $paths.DestinationPath) {
    Remove-Item -Recurse -Force -LiteralPath $paths.DestinationPath
  }

  if (Test-Path -LiteralPath $paths.ExtractDir) {
    Remove-Item -Recurse -Force -LiteralPath $paths.ExtractDir
  }

  New-Item -ItemType Directory -Force -Path $paths.RunDir | Out-Null
  Write-Host "Downloading $($paths.ZipUrl)"
  Invoke-WebRequest -UseBasicParsing $paths.ZipUrl -OutFile $paths.ZipPath

  Write-Host "Extracting XiaoZhi server"
  Expand-Archive -Force -LiteralPath $paths.ZipPath -DestinationPath $paths.RunDir
  Move-Item -LiteralPath $paths.ExtractDir -Destination $paths.DestinationPath

  $serverDir = Join-Path $paths.DestinationPath "main\xiaozhi-server"
  $dataDir = Join-Path $serverDir "data"
  New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
  Update-XiaoZhiDeviceMetadataPatch -ServerDir $serverDir

  Write-Host "Prepared XiaoZhi server at $serverDir"
  Write-Host "Next: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\render_xiaozhi_config.ps1"
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-XiaoZhiSetup -Destination $Destination -Force:$Force
}
