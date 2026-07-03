# Buddy Core 局域网集成实施计划

## 目标

先在局域网内跑通 ESP32 硬件闭环：保留 XiaoZhi 的 OTA / WebSocket / Opus / ASR / TTS 协议壳，把对话核心替换为新的 Buddy Core，并用 `device-id` 区分不同孩子。

## 第一阶段：本地实验闭环

1. 备份当前 SQLite memory 数据库和本地 XiaoZhi 配置。
2. 保留 `8003` 作为 OTA/HTTP，`8000` 作为硬件 WebSocket。
3. 将 `8010` 服务命名为 `Buddy Core`。
4. 保留 OpenAI-compatible `/v1/chat/completions` 调试入口。
5. 让 XiaoZhi 本地 LLM provider 调用 `8010`，并传入：
   - `metadata.device_id`
   - `metadata.session_id`
6. Buddy Core 根据 `device-id` 选择孩子身份和 memory profile。
7. 人格配置第一版写在配置文件里，默认 `cheerful`。
8. ASR/TTS 第一版继续使用 XiaoZhi 当前已验证链路。
9. LLM 第一版默认 DeepSeek API，同时保留后续本地模型接口。
10. `/memory` 面板改成多设备视角，可选择设备查看记忆。
11. `/memory/reset` 只清理当前选中设备的数据。

## 第二阶段：正式替换服务器

1. 从 XiaoZhi Server 中抽出必要协议行为：
   - OTA 响应
   - WebSocket 握手
   - hello/listen/audio 协议
   - Opus 音频收发
2. 在我们自己的服务中实现 `xiaozhi_compat` 层。
3. 将 Buddy Core 从调试服务升级为正式硬件服务核心。
4. 逐步替换 ASR/TTS：
   - 先保持现有接口
   - 后续可接 integrated-v1 的 Sherpa/Kokoro
5. 旧 Buddy Brain 不再作为独立服务保留。

## 验收标准

- ESP32 能通过局域网 OTA 拿到正确配置。
- ESP32 能连上 `8000` WebSocket。
- 录音能进入服务并完成 ASR。
- Buddy Core 能收到 `device-id`。
- 回复逻辑走新的 Buddy Core，而不是旧 Buddy Brain。
- 记忆按 `device-id` 分开保存。
- `/memory` 能切换设备查看记忆。
- reset 只清理当前设备。
- TTS 音频能返回并在板子播放。
- 旧 demo memory 清理前必须先备份。

## 关键风险

- XiaoZhi 默认 OpenAI provider 不会自动传 `device-id`，必须改本地 provider。
- 第一阶段还没有完全替换 XiaoZhi Server，只是替换业务核心。
- `integrated-v1` 的 `server.py` 不直接照搬，只抽取核心逻辑。
- 当前工作区已有未提交修改，实施时不能覆盖已有改动。
