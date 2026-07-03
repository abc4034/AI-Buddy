param(
  [string]$ConfigPath = ".run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml",
  [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server"
)

$ErrorActionPreference = "Stop"

function Test-ListeningPort {
  param([int]$Port)

  $connection = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { [int]$_.LocalPort -eq $Port } |
    Select-Object -First 1
  return [bool]$connection
}

function Test-ConfigFlag {
  param(
    [string]$Text,
    [string]$Pattern
  )

  return $Text -match [regex]::Escape($Pattern)
}

function Invoke-CheckLocalDemoStatus {
  param(
    [string]$ConfigPath = ".run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml",
    [string]$ServerDir = ".run\xiaozhi-esp32-server\main\xiaozhi-server"
  )

  $configText = ""
  if (Test-Path -LiteralPath $ConfigPath) {
    $configText = Get-Content -LiteralPath $ConfigPath -Raw
  }

  $providerPath = Join-Path $ServerDir "core\providers\llm\openai\openai.py"
  $connectionPath = Join-Path $ServerDir "core\connection.py"
  $providerText = if (Test-Path -LiteralPath $providerPath) { Get-Content -LiteralPath $providerPath -Raw } else { "" }
  $connectionText = if (Test-Path -LiteralPath $connectionPath) { Get-Content -LiteralPath $connectionPath -Raw } else { "" }

  [pscustomobject]@{
    Ports = [ordered]@{
      "8000" = Test-ListeningPort -Port 8000
      "8003" = Test-ListeningPort -Port 8003
      "8010" = Test-ListeningPort -Port 8010
    }
    Config = [ordered]@{
      Exists = Test-Path -LiteralPath $ConfigPath
      BuddyCoreLLM = Test-ConfigFlag -Text $configText -Pattern "BuddyCoreLLM"
      BaseUrl8010 = ($configText -match "base_url:\s+http://.+:8010/v1")
      ForwardDeviceMetadata = Test-ConfigFlag -Text $configText -Pattern "forward_device_metadata: true"
    }
    RuntimePatch = [ordered]@{
      ProviderMetadata = (
        (Test-ConfigFlag -Text $providerText -Pattern "forward_device_metadata") -and
        (Test-ConfigFlag -Text $providerText -Pattern 'metadata["device_id"] = device_id')
      )
      ConnectionMetadata = (
        (Test-ConfigFlag -Text $connectionText -Pattern "llm_kwargs = {}") -and
        (
          (Test-ConfigFlag -Text $connectionText -Pattern 'self.headers.get("client-id", self.device_id)') -or
          (Test-ConfigFlag -Text $connectionText -Pattern "client_id")
        )
      )
    }
  }
}

if ($MyInvocation.InvocationName -ne ".") {
  Invoke-CheckLocalDemoStatus -ConfigPath $ConfigPath -ServerDir $ServerDir |
    ConvertTo-Json -Depth 5
}
