# Memory 面板说明

Memory 面板是当前 demo 的本地调试工具，用来确认真实 ESP32 或调试设备的 `device_id` 是否正确映射到 profile 和 memory。

当前阶段仍按 Windows + PowerShell + conda `xiaozhi-env` 跑 demo。先启动 Buddy Core：

```powershell
conda activate xiaozhi-env
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_buddy_core.ps1
```

## 打开面板

Buddy Core 启动后，打开：

```text
http://127.0.0.1:8010/memory
```

如果已经有设备数据，页面会显示设备列表，并默认选择最近活跃的设备。页面里重点看这些字段：

- `Device`：当前选中的 `device_id`。
- `Client ID`：XiaoZhi 侧传来的 client id，若没有则通常回退到 device id。
- `User ID`：Buddy Core 内部 user_id。
- `Name`、`Age Group`、`English Level`：当前 child profile。
- 最近对话。
- 最近 memory 更新事件。

## 按 `device_id` 查看

可以直接用 query string 选设备：

```text
http://127.0.0.1:8010/memory?device_id=debug-device-a
```

真实硬件 `device-id` 常见格式带冒号，例如：

```text
fc:01:2c:cf:17:54
```

放进 URL 时必须 URL encode：

```text
http://127.0.0.1:8010/memory?device_id=fc%3A01%3A2c%3Acf%3A17%3A54
```

PowerShell 里可以这样生成：

```powershell
[uri]::EscapeDataString("fc:01:2c:cf:17:54")
```

如果不 encode，冒号、空格或其他特殊字符可能让链接和 reset action 指向错误设备。

## Reset 行为

Memory 面板里的 reset 只清理当前选中的设备。

实际行为是：

- 先用当前 `device_id` 找到对应 `user_id`。
- 删除这个 `user_id` 下的最近对话、session 和 memory events。
- 重新创建这个设备对应的默认 profile 或 `config/devices.yaml` 中配置的 profile。
- 不清理其他设备的 memory。

直接调用时也要 encode：

```powershell
Invoke-WebRequest -Method Post "http://127.0.0.1:8010/memory/reset?device_id=fc%3A01%3A2c%3Acf%3A17%3A54"
```

当前设计默认一台设备对应一个孩子/user_id。不要把多个真实孩子共用同一个 `device_id`，否则 reset 会按同一个 user_id 清理。

## Demo 前先备份

在硬件 demo、reset memory、重渲染 XiaoZhi 配置之前，先备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup_local_demo_data.ps1
```

备份脚本会在文件存在时复制：

- `data\buddy_memory.db`
- `.run\xiaozhi-esp32-server\main\xiaozhi-server\data\.config.yaml`

这一步很便宜，但能避免 demo 前误删真实硬件设备的记忆。

## 调试两个设备

不连硬件时，也可以用不同 `device_id` 模拟两个孩子：

```text
debug-device-a -> profile A -> memory A
debug-device-b -> profile B -> memory B
```

Buddy Core 启动后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_two_devices.ps1
```

脚本会调用两次 `smoke_chat.ps1`，分别传入 `debug-device-a` 和 `debug-device-b`，然后打印两个 `/memory?device_id=...` 链接。

如果两个设备的页面显示相同 `user_id` 或互相串 memory，优先检查：

- 请求 metadata 里是否真的传了不同的 `device_id`。
- XiaoZhi provider patch 是否还在。
- `config/devices.yaml` 里的设备 id 是否和真实传入值完全一致。
- URL 里的 `device_id` 是否做了 URL encode。
