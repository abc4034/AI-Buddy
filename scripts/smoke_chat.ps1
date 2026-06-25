$ErrorActionPreference = "Stop"

$greeting = [string]([char]0x4f60) + [string]([char]0x597d)
$content = "$greeting Buddy, I like dinosaurs. Can you teach me one English sentence?"

$body = @{
  model = "deepseek-v4-flash"
  stream = $false
  messages = @(
    @{
      role = "user"
      content = $content
    }
  )
} | ConvertTo-Json -Depth 5

Add-Type -AssemblyName System.Net.Http

$client = [System.Net.Http.HttpClient]::new()
try {
  $requestBody = [System.Net.Http.StringContent]::new(
    $body,
    [System.Text.Encoding]::UTF8,
    "application/json"
  )
  $response = $client.PostAsync(
    "http://127.0.0.1:8010/v1/chat/completions",
    $requestBody
  ).Result
  $response.EnsureSuccessStatusCode() | Out-Null
  $bytes = $response.Content.ReadAsByteArrayAsync().Result
  [System.Text.Encoding]::UTF8.GetString($bytes)
} finally {
  $client.Dispose()
}
