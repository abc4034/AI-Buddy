# AI Buddy 局域网硬件 Demo 设计

日期：2026-06-25

## 目标

第一版先跑通一个局域网内的英语陪伴教育 demo，硬件使用当前这套 ESP32-S3 小智兼容设备，服务端接入我们自己的 Buddy 教育逻辑。

这个 demo 需要证明：

- ESP32 设备可以把语音输入送进我们自己的本地服务链路。
- 系统能处理中英混合输入。
- Buddy 能用适合儿童的中英混合风格回答。
- 长期记忆能跨服务重启保留。
- 模型默认走 DeepSeek 的 OpenAI-compatible API，同时保留未来切换本地 vLLM 的接口。

当前硬件的喇叭路径暂时不作为第一版验收条件。根据照片和串口日志，设备已经进入播放状态，但疑似缺少 MAX98357A I2S 数字功放或喇叭接线，所以第一版先用屏幕、串口日志、服务端日志和 SQLite 数据库验证闭环。

## 当前硬件状态

已经通过 USB 串口确认：

- 串口：`COM8`
- 芯片：`ESP32-S3 (QFN56) revision v0.2`
- MAC：`fc:01:2c:cf:17:54`
- PSRAM：8 MB
- Flash：16 MB
- 当前固件项目：`xiaozhi`
- 当前固件版本：`1.6.0`
- 当前板型 SKU：`bread-compact-wifi-lcd`
- 当前云端 OTA：`https://api.tenclass.net/xiaozhi/ota/`
- 当前云端 MQTT：`mqtt.xiaozhi.me`
- 测试时设备局域网 IP：`192.168.2.14`

已经可用：

- Wi-Fi 联网
- 屏幕
- 麦克风输入
- 小智云端 ASR 和回答生成
- 串口日志
- 回答时绿色播放状态灯

已知硬件缺口：

- 喇叭没有声音。日志显示固件进入 `speaking` 并执行 `AudioCodec: Set output enable to true`，所以更可能是 MAX98357A 功放或喇叭接线问题。这不阻塞服务端 demo。

## 推荐架构

硬件侧复用小智固件和协议，教育能力放在服务端。

```text
ESP32-S3 小智固件
  -> 小智 OTA/WebSocket 协议
  -> 本地 xiaozhi-server
  -> Buddy Brain OpenAI-compatible LLM 服务
  -> DeepSeek API
  -> SQLite 长期记忆
```

### 为什么这样做

ESP32 固件已经处理设备状态、麦克风采集、屏幕、Opus 音频、Wi-Fi、OTA 和小智协议。重写这些硬件链路风险高，而且对英语教育产品的核心价值帮助不大。

两套现有代码不直接硬拼，而是抽取能力：

- `abc4034/AI-Buddy`：实时语音管线、OpenAI-compatible/vLLM 接入、部署经验。
- `Milky997/buddy`：儿童英语提示词、人设、纠错、词汇提示、水平判断、SQLite 记忆思路。

第一版应整理成一个边界清晰的新服务，而不是把两个仓库逐文件合并。

## 服务划分

### `xiaozhi-server`

职责：

- 接收设备 OTA 请求。
- 向设备下发局域网 WebSocket 地址。
- 处理小智设备协议。
- 第一版使用最容易跑通的 ASR/TTS 配置。
- 把 LLM 请求转给 Buddy Brain。

配置方向：

- 优先跑在 Ubuntu 22 虚拟机中。
- 虚拟机网络使用桥接模式，让 ESP32 可以直接访问虚拟机局域网 IP。
- `server.websocket` 设置为虚拟机局域网地址，例如 `ws://192.168.2.x:8000/xiaozhi/v1/`。
- `server.vision_explain` 设置为虚拟机局域网地址，例如 `http://192.168.2.x:8003/mcp/vision/explain`。
- 第一版关闭小智服务端自己的 Memory，避免和 Buddy Brain 的记忆系统互相污染。

### `buddy-brain`

职责：

- 暴露 OpenAI-compatible 的 `/v1/chat/completions` 接口。
- 接收 `xiaozhi-server` 传来的对话。
- 把设备或 session 映射到 Buddy 用户。
- 从 SQLite 读取用户画像和最近历史。
- 构造儿童友好的中英陪伴教育 prompt。
- 通过 OpenAI-compatible client 调用 DeepSeek。
- 返回流式或非流式 chat completion。
- 记录原始对话，并异步更新长期记忆。

模型配置保持供应商无关：

```text
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=从环境变量读取
MODEL_NAME=deepseek-v4-flash
```

未来切本地模型时只改配置：

```text
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=not-needed
MODEL_NAME=本地模型名称或路径
```

API key 不写入代码、文档或 git。

## 记忆设计

第一版使用本地 SQLite：

```text
data/buddy_memory.db
```

### 数据表

`devices`

- 设备身份到用户身份的映射。
- 关键字段：`device_id`、`client_id`、`user_id`、`created_at`、`last_seen_at`。

`users`

- demo 用户基础信息。
- 关键字段：`user_id`、`display_name`、`created_at`、`updated_at`。

`profile`

- 长期用户画像。
- 关键字段：`user_id`、`name`、`age_group`、`english_level`、`interests_json`、`language_preference`、`learning_goals_json`、`notes_json`、`updated_at`。

`sessions`

- 每次设备连接或对话会话。
- 关键字段：`session_id`、`user_id`、`device_id`、`started_at`、`ended_at`。

`episodes`

- 每轮原始对话。
- 关键字段：`episode_id`、`session_id`、`user_id`、`user_text`、`assistant_text`、`detected_language`、`created_at`。

`memory_events`

- 每次模型提取出的记忆变更，方便回溯和调试。
- 关键字段：`event_id`、`episode_id`、`user_id`、`event_type`、`payload_json`、`created_at`、`applied_at`。

### 每轮对话流程

1. 根据设备创建或加载用户。
2. 读取用户画像。
3. 读取最近 5 到 10 轮对话。
4. 构造简洁 prompt，包含：
   - Buddy 人设
   - 儿童安全和教育边界
   - 中英回答策略
   - 用户画像
   - 最近历史
5. 调 DeepSeek 生成回复。
6. 写入原始对话到 `episodes`。
7. 后台异步调用模型提取结构化记忆。
8. 把稳定、安全的事实合并到 `profile`。
9. 把所有记忆变更记录到 `memory_events`。

### 默认 demo 用户

没有真实 onboarding 前先使用默认用户：

```json
{
  "name": "Mia",
  "age_group": "primary school",
  "english_level": "beginner",
  "interests": ["animals", "drawing", "games"],
  "language_preference": "English first, Chinese explanation when needed",
  "learning_goals": ["speak simple English sentences", "build confidence"],
  "style": "70% warm companion, 30% gentle teaching"
}
```

## 对话风格

Buddy 应该：

- 接受中文、英文和中英混合输入。
- 优先用英语回答，需要时用简短中文解释。
- 回复要短，适合儿童，也方便后续低延迟 TTS。
- 每轮最多问一个自然的追问。
- 每轮最多纠正一个明确英语错误。
- 只在有帮助时引入一个新词。
- 避免长篇语法课。
- 记住稳定的兴趣、名字、水平和学习偏好。

策略示例：

```text
如果孩子用中文问，使用简单英语回答，并附一句简短中文解释。
如果孩子用英文问，主要用英文回答。
如果孩子卡住，给两个简单选项。
```

## 第一版验收标准

第一版 demo 成功条件：

1. ESP32 通过局域网连接到本地 XiaoZhi 服务端。
2. 串口或服务端日志中能看到中文或英文语音被识别成文本。
3. Buddy Brain 收到该轮对话并调用 DeepSeek。
4. Buddy Brain 返回儿童友好的中英混合回答。
5. 回答出现在日志中，若当前固件支持，也出现在屏幕上。
6. `episodes` 写入该轮对话。
7. 对值得记忆的内容，`profile` 或 `memory_events` 有更新。
8. 重启 Buddy Brain 后，长期记忆仍然存在。

当前硬件第一版不要求喇叭有声音。

## 实施阶段

### 阶段 1：本地文本链路

- 创建 `buddy-brain`。
- 接入 DeepSeek OpenAI-compatible client。
- 建 SQLite schema 和默认用户。
- 提供 `/health`。
- 提供 `/v1/chat/completions`。
- 先用本地 `curl` 测试，不接硬件。

### 阶段 2：记忆链路

- 存储原始对话。
- 注入最近历史。
- 添加异步记忆提取。
- 添加用户画像合并规则。
- 验证重启后记忆保留。

### 阶段 3：小智服务端集成

- 本地运行 `xiaozhi-server`。
- 配置 LLM provider 指向 `buddy-brain`。
- ASR/TTS 先使用最容易跑通的方案。
- 确认本地日志能看到 Buddy Brain 的回答。

### 阶段 4：硬件路由

- 把 ESP32 指向本地 OTA/WebSocket。
- 如果无法运行时修改 OTA URL，就编译或刷入兼容 `bread-compact-wifi-lcd` 的本地 OTA 固件。
- 验证硬件到本地服务端的完整链路。

### 阶段 5：后续音频修复

- 补齐或更换 MAX98357A 功放路径。
- 重测播放。
- 再调 TTS 音色和延迟。

## 风险与处理

`ota_url` 仍然指向小智云端。

- 处理：优先尝试设备设置；不行就编译带本地 `CONFIG_OTA_URL` 的固件。

ASR 可能被配置成偏中文。

- 处理：第一版选择支持中英混合或自动语言识别的 ASR 配置。

小智服务端和 Buddy Brain 都管理记忆。

- 处理：第一版关闭小智 Memory，Buddy Brain 作为唯一记忆来源。

DeepSeek 延迟或额度影响响应。

- 处理：prompt 保持短，默认用 `deepseek-v4-flash`，同时保留本地 vLLM 配置口。

当前硬件没有喇叭输出。

- 处理：第一版用日志、屏幕、数据库验收，硬件音频后续单独修。

## 第一版不做

- 精致前端管理后台。
- 生产级认证。
- 多儿童 onboarding 界面。
- 高质量定制 TTS 音色。
- 公网云部署。
- 本地 GPU 模型服务。
- 喇叭或功放维修。
