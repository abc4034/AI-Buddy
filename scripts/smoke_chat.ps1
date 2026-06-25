$ErrorActionPreference = "Stop"

$body = @{
  model = "deepseek-v4-flash"
  stream = $false
  messages = @(
    @{
      role = "user"
      content = "你好 Buddy, I like dinosaurs. Can you teach me one English sentence?"
    }
  )
} | ConvertTo-Json -Depth 5

curl.exe -s `
  -H "Content-Type: application/json" `
  -d $body `
  http://127.0.0.1:8010/v1/chat/completions
