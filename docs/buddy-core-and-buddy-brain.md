# Buddy Core 与旧 Buddy Brain 的关系

对外汇报和新文档里，我们叫它 **Buddy Core**。代码包名暂时仍然是 `buddy_brain`。

这不是两个并行服务。Buddy Core 是从原来的 Buddy Brain 服务演进出来的业务核心，只是当前阶段为了降低风险，没有立刻重命名 Python package、模块路径和部分兼容脚本。

## 为什么代码包还叫 `buddy_brain`

短期保留 `buddy_brain` 有几个现实原因：

- 现有 FastAPI 入口仍是 `buddy_brain.app:app`。
- 测试、脚本、导入路径都依赖这个包名。
- 当前目标是稳定 Windows 局域网 demo，不适合把包重命名变成大范围改动。
- 保留旧名字可以让已有脚本和调试方式继续可用。

所以看到这些名字时，可以这样理解：

- `Buddy Core`：对外产品/业务核心名称。
- `buddy_brain`：当前 Python package 名，是历史兼容名。
- `Buddy Brain`：旧称。现在只用于解释来源，不再作为新的对外服务名。

## 当前系统边界

当前链路是：

```text
ESP32-S3 小智固件
  -> XiaoZhi Server 协议层 / 音频层
  -> BuddyCoreLLM OpenAI-compatible 适配
  -> Buddy Core
  -> LLM / Profile / Persona / Memory
```

XiaoZhi Server 仍然保留，负责硬件协议和音频链路：

- OTA 地址下发。
- WebSocket 连接。
- 小智协议兼容。
- Opus 音频收发。
- 当前 demo 使用的 ASR/TTS 链路。
- 把硬件 `device-id` 转发进 Buddy Core metadata。

Buddy Core 负责业务核心：

- 根据 `device_id` 找到或创建孩子身份。
- 维护 child profile。
- 选择 persona。
- 组合 prompt。
- 调用 LLM。
- 写入和读取 SQLite memory。
- 提供 `/memory` 本地调试面板。
- 保留 `/v1/chat/completions` 作为接入和调试入口。

一句话讲清楚：当前阶段替换的是“业务大脑”，不是整个小智服务器。

## 和 Buddy Device Gateway 的关系

Buddy Device Gateway 是下一阶段逐步替换 XiaoZhi Server 的新协议服务。v0.1 已经开始实现，但只做到协议骨架：

- 保持 OTA/HTTP `8003` 和 WebSocket `8000` 端口兼容。
- 让 ESP32 从新 Gateway 获取 `/xiaozhi/v1/` WebSocket 地址。
- 记录真实硬件的 `device-id`、`client-id`、`hello`、`listen` 和音频 bytes。
- 暂时不做 Opus 解码、ASR、Buddy Core 调用、TTS 或音频回复。

所以现阶段有两条清晰路径：

- 已跑通语音闭环的 demo：继续使用 XiaoZhi Server 作为协议层和音频层，Buddy Core 作为业务核心。
- 新的替换路线：使用 Buddy Device Gateway v0.1 验证协议入口和硬件连接。

仍然不把这些事情作为 v0.1 交付：

- 不重写 ESP32 固件。
- 不声称已经完整替换 XiaoZhi Server。
- 不自研完整 OTA/WebSocket/Opus/ASR/TTS 闭环。
- 不把 Python package 从 `buddy_brain` 立刻改名。

## 对外怎么说

推荐说法：

```text
Buddy Core 是从原 Buddy Brain 服务演进来的业务核心。
当前代码包名仍保留 buddy_brain，是为了降低重命名风险。
XiaoZhi Server 现在仍作为协议和音频层，Buddy Core 负责 profile、persona、memory 和 LLM。
Buddy Device Gateway v0.1 已开始验证替换 XiaoZhi Server 的协议入口，但还不是完整语音闭环。
```

避免说法：

```text
我们已经完全替换了 XiaoZhi Server。
Buddy Brain 和 Buddy Core 是两个服务。
当前阶段要重写 ESP32 固件。
Buddy Device Gateway v0.1 已经支持 ASR/TTS 回复。
```
