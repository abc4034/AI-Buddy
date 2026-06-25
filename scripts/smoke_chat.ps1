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

curl.exe -s `
  -H "Content-Type: application/json" `
  -d $body `
  http://127.0.0.1:8010/v1/chat/completions
