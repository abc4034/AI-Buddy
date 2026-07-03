# Buddy Core 局域网 Demo 中间总结

这份记录只是当前中间过程的轻量总结，不是正式汇报稿。目标是把两轮主要更新、验证结果和下一步方向先固化下来，方便后续继续开发或回看进度。

## 第一次更新：跑通局域网硬件闭环

第一轮重点是先把 ESP32 小智硬件接到我们自己的 Buddy Core 业务逻辑上。

当时采用的是保守架构：不重写 ESP32 固件，也不立刻替换 XiaoZhi Server，而是继续让 XiaoZhi Server 负责 OTA、WebSocket、Opus 音频、ASR 和 TTS 协议层。Buddy Core 作为新的业务大脑，通过 OpenAI-compatible `/v1/chat/completions` 接口被 XiaoZhi Server 调用。

这一轮主要完成了：

- 新增 XiaoZhi 配置渲染流程，把 LLM provider 指向本机 Buddy Core。
- 保留 `8003` 作为 OTA/HTTP 端口，`8000` 作为硬件 WebSocket 端口，`8010` 作为 Buddy Core 端口。
- 增加 XiaoZhi runtime patch，把真实 ESP32 连接里的 `device-id`、`client-id`、`session-id` 转发进 Buddy Core metadata。
- 新增本地启动和 URL 打印脚本，减少手动配置错误。
- 生成第一版系统架构图：`docs/architecture/buddy-step1-system-architecture-clean.png`。
- 跑通 ESP32 语音输入、ASR、Buddy Core 回复、TTS 播放的硬件闭环。

这一轮的核心结论是：我们已经证明“保留 XiaoZhi 协议层，把业务大脑替换成 Buddy Core”这条路线可行。

## 本次更新：固化 demo 并增强 Buddy Core

第二轮重点是把已经跑通的 PoC 变得更稳定、更容易复测，也让 Buddy Core 更像后续业务核心，而不只是一个转发接口。

这一轮主要完成了：

- 补齐 Windows 本地 demo 固化脚本：
  - `scripts/start_buddy_core.ps1`
  - `scripts/check_local_demo_status.ps1`
  - `scripts/backup_local_demo_data.ps1`
  - `scripts/stop_local_demo.ps1`
  - `scripts/smoke_two_devices.ps1`
- 明确当前阶段只支持 Windows PowerShell + conda `xiaozhi-env` 作为验收路径。
- 增强 `device-id -> user_id -> profile -> memory` 映射，让不同设备对应不同孩子资料和记忆。
- 增加 `config/devices.example.yaml`，为后续真实设备配置孩子 profile 和 persona 留好入口。
- 增加三种 persona：`cheerful`、`calm`、`coach`，并让它们在 prompt 行为上有可观察差异。
- 保留并增强 `/memory` 面板，支持按设备查看、URL encode、单设备 reset、client/user/device 信息展示。
- 增加 TTS 友好处理，减少 Markdown、代码符号、列表符号和 emoji 进入硬件朗读路径。
- 补齐配置说明、Memory 面板说明，以及 Buddy Core 和旧 Buddy Brain 命名关系说明。

这一轮的核心结论是：当前 demo 已经从“能跑通”推进到“能稳定复测和解释架构”。

## 当前验证结果

已确认的验证点：

- 自动化测试通过：`89 passed, 1 warning`。
- `check_local_demo_status.ps1` 可以检查 `8000`、`8003`、`8010` 端口，以及 XiaoZhi 配置和 runtime patch。
- `smoke_chat.ps1` 可以直接调用 Buddy Core。
- `smoke_two_devices.ps1` 可以模拟两个不同 `device-id`，并打印对应的 Memory 面板链接。
- 真实 ESP32 硬件 OTA、WebSocket、ASR、Buddy Core 回复、TTS 播放链路已确认可用。
- 真实硬件 `device-id` 已经能进入 Buddy Core，并写入 SQLite memory。

复测时最短命令：

```powershell
conda run -n xiaozhi-env python -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_demo_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_two_devices.ps1
```

硬件复测时，先确认电脑和 ESP32 在同一个 WiFi，再使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\print_local_demo_urls.ps1
```

把打印出的 `XiaoZhi OTA URL` 填到 ESP32。

## 下一步路线

短期建议继续先稳定 Buddy Core 和演示流程：

- 汇报或演示前多跑几轮硬件复测，尤其注意换 WiFi 后 LAN IP 和 OTA URL 会变化。
- 根据真实孩子使用情况继续调整 persona、profile 和 memory 质量。
- 保持 XiaoZhi Server 作为协议层，不急着重写硬件服务器。

阶段 C 的自研 Buddy Device Gateway 暂时只作为后续路线图。只有在阶段 A/B 稳定、协议日志足够、继续兼容现有 ESP32 小智固件的前提没有被推翻之后，再开始替换 XiaoZhi Server 的协议层和音频链路。
