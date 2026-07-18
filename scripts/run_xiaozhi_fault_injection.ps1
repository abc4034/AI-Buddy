[CmdletBinding()]
param(
    [ValidateSet("timeout", "http_500", "malformed", "partial_tts_failure")]
    [string]$Mode = "timeout",
    [int]$FaultPort = 18081
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$faultDirectory = Join-Path $repoRoot "tmp\fault-config"
$faultConfig = Join-Path $faultDirectory "fault-config.yaml"
$serverProcess = $null
$cleanupError = $null

New-Item -ItemType Directory -Force -Path $faultDirectory | Out-Null
@"
buddy_mode: true
fault_test_mode: true
manager-api: {url: '', secret: ''}
read_config_from_api: false
server: {ip: 127.0.0.1, port: 18000, http_port: 18003}
selected_module: {ASR: BuddyFaultASR, LLM: BuddyCoreLLM, Memory: nomem, Intent: nointent, TTS: BuddyFaultTTS}
ASR: {BuddyFaultASR: {type: buddy_fault, base_url: http://127.0.0.1:$FaultPort, timeout_seconds: 1}}
LLM: {BuddyCoreLLM: {type: buddy_core, base_url: http://127.0.0.1:18010}}
TTS: {BuddyFaultTTS: {type: buddy_qwen_http, api_url: http://127.0.0.1:$FaultPort, api_key: fault-test-placeholder, model: fault-test-model, voice: Cherry}}
Memory: {nomem: {type: nomem}}
Intent: {nointent: {type: nointent}}
end_prompt: {enable: false}
tools: {enable: false}
report: {enable: false}
VLLM: {enable: false}
context_providers: []
voiceprint: false
prompt: ''
prompt_template: buddy-neutral-prompt.txt
"@ | Set-Content -Encoding utf8 -Path $faultConfig

try {
    $pythonExe = (& conda run -n xiaozhi-env python -c "import sys; print(sys.executable)" | Select-Object -Last 1).Trim()
    if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "Could not resolve the xiaozhi-env Python executable."
    }
    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList @("tests/fixtures/fault_provider_server.py", "--port", $FaultPort, "--mode", $Mode) -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "conda"
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    [void]$startInfo.ArgumentList.Add("run")
    [void]$startInfo.ArgumentList.Add("-n")
    [void]$startInfo.ArgumentList.Add("xiaozhi-env")
    [void]$startInfo.ArgumentList.Add("python")
    [void]$startInfo.ArgumentList.Add("xiaozhi_server/app.py")
    $startInfo.Environment["BUDDY_FAULT_TEST_MODE"] = "1"
    $startInfo.Environment["BUDDY_XIAOZHI_CONFIG_PATH"] = $faultConfig
    $runtime = [System.Diagnostics.Process]::Start($startInfo)
    $runtime.WaitForExit()
    exit $runtime.ExitCode
}
finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    if ($serverProcess) {
        if (-not $serverProcess.WaitForExit(5000)) {
            $cleanupError = "Fault provider process did not exit after cleanup."
        }
        $serverProcess.Dispose()
    }
    Remove-Item Env:BUDDY_FAULT_TEST_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:BUDDY_XIAOZHI_CONFIG_PATH -ErrorAction SilentlyContinue
    if ($cleanupError) {
        throw $cleanupError
    }
}
