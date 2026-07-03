# Buddy Core 配置说明

这份文档只覆盖当前 demo 阶段：Windows + PowerShell + conda `xiaozhi-env`。Ubuntu、普通 venv、Docker 和公网部署可以以后再整理，不作为当前验收路径。

## 配置入口

Buddy Core 目前主要从两个地方读配置：

- `.env`：运行时配置，控制模型入口、API key、默认 persona、数据库路径等。
- `config/devices.yaml`：设备到孩子 profile/persona 的映射文件。仓库里有 `config/devices.example.yaml` 作为模板；真正生效的文件名是 `config/devices.yaml`。

不要提交真实 `.env`。如果 `config/devices.yaml` 里写了真实孩子信息或真实设备号，也要按本地敏感配置处理。

## `.env`

从模板复制：

```powershell
Copy-Item .env.example .env
```

当前默认值类似这样：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=
MODEL_NAME=deepseek-v4-flash
PERSONA=cheerful
DATABASE_PATH=data/buddy_memory.db
```

常用字段：

- `OPENAI_BASE_URL`：OpenAI-compatible 服务地址。默认指向 DeepSeek，也可以切到本地模型服务。
- `OPENAI_API_KEY`：本地私密 key，只写在 `.env` 或环境变量里。
- `MODEL_NAME`：主对话模型名。
- `MEMORY_MODEL_NAME`：可选。留空时复用 `MODEL_NAME` 做记忆抽取。
- `PERSONA`：默认人格。设备没有单独配置 persona 时使用它。
- `DATABASE_PATH`：SQLite memory 数据库路径，默认是 `data/buddy_memory.db`。
- `DEVICE_CONFIG_PATH`：可选。默认读取 `config/devices.yaml`。

本地模型切换仍走同一个 API 面：

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8001/v1
OPENAI_API_KEY=
MODEL_NAME=local-model-name
```

## `config/devices.yaml`

`config/devices.yaml` 用来把真实硬件或调试设备映射到孩子 profile。文件不存在时，Buddy Core 会使用默认 profile，并按收到的 `device_id` 自动建档。

示例：

```yaml
devices:
  debug-device-a:
    child_name: Mia
    age_group: primary school
    english_level: beginner
    persona: cheerful

  debug-device-b:
    child_name: Luna
    age_group: kindergarten
    english_level: starter
    persona: calm

  "fc:01:2c:cf:17:54":
    child_name: Demo Child
    age_group: primary school
    english_level: beginner
    persona: coach
```

真实 ESP32 的 `device-id` 可能带冒号，建议在 YAML 里加引号。仓库模板 `config/devices.example.yaml` 可以直接参考，但模板文件本身不会自动生效。

当前第一版 profile 字段保持很小：

- `child_name`：Memory 面板和 prompt 中展示的孩子名字。
- `age_group`：年龄段，例如 `kindergarten`、`primary school`。
- `english_level`：英语水平，例如 `starter`、`beginner`。
- `persona`：该设备使用的人格。没有配置时回退到 `.env` 的 `PERSONA`。

## 设备到记忆的映射

Buddy Core 用 `device-id -> user_id -> profile -> memory` 这条链路分开不同孩子的数据。

1. XiaoZhi Server 从 ESP32 连接里拿到硬件 `device-id`。
2. XiaoZhi 的 OpenAI provider patch 把它转成 chat metadata 里的 `device_id`。
3. Buddy Core 优先读 `metadata.device_id`，也兼容 `metadata.device-id`。
4. 如果这个 `device_id` 已经存在，沿用已有 `user_id`。
5. 如果是新设备，Buddy Core 会生成 `user_id`，形如 `device-fc-01-2c-cf-17-54`。
6. `profile` 属于这个 `user_id`。
7. `episodes`、`sessions`、`memory_events` 也按同一个 `user_id` 写入 SQLite。

所以同一块 ESP32 反复对话时会回到同一个 profile 和 memory。调试时换一个 `device_id`，就会看到另一个孩子的 profile 和 memory。

## Persona

当前保留三种 persona，都是为了 TTS 语音回复服务的，不只是改名字：

- `cheerful`：默认人格。更活泼、鼓励感更强，适合普通演示和低压力互动。
- `calm`：更慢、更温柔、更有耐心，适合孩子紧张、答错或需要安抚时。
- `coach`：更像小教练，会给一个很小的挑战，再邀请孩子试一次。

无论哪种 persona，Buddy Core 都会尽量保持短句、少 Markdown、一次只纠正一个明显问题，避免 TTS 读起来太长或太怪。

## OpenAI-compatible 入口

`/v1/chat/completions` 暂时继续保留。它有两个用途：

- XiaoZhi Server 把 Buddy Core 当作 OpenAI-compatible LLM provider 调用。
- 本地调试可以不连硬件，直接用 smoke test 或脚本模拟不同 `device_id`。

这不是说 Buddy Core 只是一个模型转发器。当前边界是：OpenAI-compatible API 负责接入，Buddy Core 内部负责 profile、persona、memory、prompt builder 和 LLM 调用。
