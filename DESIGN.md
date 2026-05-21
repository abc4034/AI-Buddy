# 语音对话服务重构设计文档

> 日期：2026-05-20
> 目标：移除 Pipecat 框架，替换 Ollama 为 vLLM，单容器部署到阿里云 PAI-EAS

---

## 1. 项目目标与范围

### 目标

将现有基于 Pipecat 框架的实时语音对话 Demo 重构为可独立部署的服务，适配 ESP32 硬件终端。

### 范围

- 移除 Pipecat 框架，用 `asyncio.Queue` + async Task 实现管线调度
- Ollama 替换为 vLLM
- 单容器 Docker 部署，适配 PAI-EAS
- 保留 ESP32（PCM 16kHz）和浏览器双客户端支持
- 保留打断（barge-in）能力——用户在 AI 说话时可以插话打断
- ConfigManager、LangGraph agent、FastSentenceAggregator 逻辑保留

### 不在此次范围

- 功能新增（RAG、工具调用恢复等）
- 多用户并发

---

## 2. 架构设计

### 2.1 部署架构

```
┌─────────────────────────────────────┐
│  单容器 (GPU)                        │
│                                     │
│  ┌──────┐  ┌──────────┐  ┌───────┐ │
│  │ vLLM │  │ Qwen TTS │  │ main  │ │
│  │:8001 │  │ :8000    │  │ :8080 │ │
│  └──────┘  └──────────┘  └───┬───┘ │
│       ↑          ↑           │     │
│       └─────┬────┘           │     │
│             │ localhost HTTP │     │
│             └────────────────┘     │
└─────────────────┬──────────────────┘
                  │ :8080 WebSocket
             ┌────┴────┐
             │ ESP32    │  (PCM 16kHz, 16bit, mono)
             │ 浏览器    │
             └─────────┘
```

- **vLLM**（LLM）和 **Qwen TTS** 作为独立子进程，并行启动
- **main** 进程通过 localhost HTTP 调用两者
- 对外只暴露 `:8080` WebSocket，PAI-EAS 负载均衡打到这个端口

### 2.2 为什么不用 Pipecat 的帧类型系统

Pipecat 定义了几十种帧类型（`LLMTextFrame`、`LLMFullResponseStartFrame`、`LLMContextFrame`、
`InputAudioRawFrame`、`OutputAudioRawFrame` 等），核心原因是它需要作为**通用框架**支持：

- **多模态**：同一管线里同时跑音频、文本、图片、视频
- **多用户**：帧带 `FrameDirection`（UPSTREAM / DOWNSTREAM）标记来源和去向
- **任意组合**：用户可能以任意顺序串联处理器，帧系统充当"通用语言"

这个项目的数据流是固定的单用户环形链路，只有 3 种数据形态：

```
音频 bytes (16kHz PCM) → 文本 str → 音频 bytes (24kHz PCM)
```

用 `asyncio.Queue[bytes]` 和 `asyncio.Queue[str]` 完全足够，不需要在 bytes 外面再包一层帧。

### 2.3 为什么不再需要 Pipecat 的分词器文件

Pipecat 的 `pipecat/utils/string.py` 依赖 NLTK 的 `punkt_tab` 分词器数据文件，
**唯一用途是句子边界检测（`match_endofsentence()`）**——判断一段文本哪里是完整句子的结尾。

NLTK 能智能区分拉丁文字中 `.` 的不同含义（句号 vs 缩写 vs 小数），但你的 `FastSentenceAggregator`
用正则匹配标点实现同样功能，不依赖 NLTK。

该文件被以下组件间接引用：

| Pipecat 组件 | 引用了 `string.py` 的什么 | 重构后 |
|---|---|---|
| `SentenceAggregator` | `match_endofsentence()` | FastSentenceAggregator（正则），不需要 |
| `LLMContextAggregatorPair` | `TextPartForConcatenation`, `concatenate_aggregated_text` | LangGraph checkpoint 管理上下文，不需要 |
| `simple_text_aggregator` | `match_endofsentence()` | 你没用到 |
| `rtvi.py` | `match_endofsentence()` | 你没用到 |

**注意**：即使你不用 `SentenceAggregator`，只要 import 了 `LLMContextAggregatorPair`，
就会触发 `string.py` 的模块级代码检查/下载 `punkt_tab`。Docker 容器内如果网络不通或
NLTK 数据目录不可写，就会报错。脱离 Pipecat 框架后该问题自然消失。

分词器和 LLM 上下文 token 计数无关——Pipecat 没有用它做 token 计数。

### 2.4 进程内管线（含打断）

```
WebSocket recv (PCM bytes)
        │
        ▼
┌──────────────────┐
│  AudioBuffer      │
│  + SpeakerDetector│
└────────┬─────────┘
         │ VAD 状态变化
         ▼
┌──────────────────┐
│  SileroVAD        │
│                   │
│  speech_start ────┼──→ 触发打断逻辑:
│                   │     1. 取消当前 TTS 流
│  speech_end ──────┼──→ 2. 清空 audio_out_queue
│                   │     3. 取消进行中的 LLM 调用
	│                   │     4. 将 LLM 已生成的部分 token 保存到 checkpoint
│                   │     4. VAD 重新累积 → STT
└────────┬─────────┘
         │ speech_end + 完整音频 bytes
         ▼
┌──────────────────┐
│  WhisperSTT       │  bytes → text
└────────┬─────────┘
         │ text
         ▼
┌──────────────────┐
│  LangGraph Agent  │  流式调 vLLM:8001
└────────┬─────────┘
         │ token 流
         ▼
┌──────────────────┐
│ SentenceSplitter  │  标点触发断句
└────────┬─────────┘
         │ 逐句文本
         ▼
┌──────────────────┐
│  TTS Client       │  调 TTS:8000 → PCM
└────────┬─────────┘
         │ PCM (24kHz)
         ▼
WebSocket send
```

### 2.5 打断流程详解

```
用户的打断不应该丢弃 LLM 的部分输出。已经生成且可能被 TTS 播放过的 token，
必须保存到 LangGraph checkpoint，这样下轮对话 LLM 才知道"我刚才说了一半被打断了"。

```
用户开始说话 (VAD speech_start)
        │
        ├─ 当前正在播放 TTS？
        │   ├─ 是 → 1. 取消 TTS 流 (取消 httpx/aiohttp 请求)
        │   │       2. 清空 audio_out_queue（丢弃排队但未播放的音频）
        │   │       3. 取消 LLM astream
        │   │       4. 将 LLM 已生成的部分 token 拼接为 partial_response
        │   │       5. 将 partial_response 作为 AIMessage 写入 LangGraph checkpoint ★
        │   │       6. VAD 重新累积用户新语音
        │   │
        │   └─ 否 → 正常 VAD 累积流程
        │
        ▼
用户说完 (VAD speech_end)
        │
        ▼
  STT → LLM → TTS (新轮对话，LLM 知道刚才被打断时说了什么)
```

实现方式：

```python
# 用 asyncio.Event 做跨 Task 信号
interrupt_event = asyncio.Event()

# vad_loop 中检测到 speech_start:
if tts_is_playing or llm_is_generating:
    interrupt_event.set()       # 通知 llm_loop / tts_loop 立即停止
    audio_out_queue.clear()     # 丢弃排队但未播放的音频

# llm_loop 中被打断时:
partial_response = ""
try:
    async for chunk, _ in agent.astream(...):
        if interrupt_event.is_set():
            break               # 停止生成
        partial_response += chunk.content
        await token_queue.put(chunk.content)
finally:
    # ★ 关键：将部分输出保存到 checkpoint
    if partial_response:
        agent.update_state(
            config,
            {"messages": [AIMessage(content=partial_response)]}
        )
    interrupt_event.clear()
```

### 2.6 并发模型：5 个 asyncio Task + 1 个 Event

```
Task 1: audio_receiver    →  WebSocket recv → audio_queue
Task 2: vad_loop          →  audio_queue → VAD → speech_end → stt_queue
                             ├─ speech_start → interrupt_event.set() (打断!)
Task 3: llm_loop           →  stt_queue → LangGraph → token_queue
                             检查 interrupt_event，被打断则保存部分输出到 checkpoint
Task 4: tts_loop           →  token_queue → 断句 → TTS API → audio_out_queue
                             检查 interrupt_event，被打断则取消 HTTP 请求
Task 5: audio_sender      →  audio_out_queue → WebSocket send
Event: interrupt_event     → 协调打断信号
```

---

## 3. 数据流与接口

### 3.1 Queue 数据结构

```python
# 管线中 4 个 asyncio.Queue：
audio_queue:      asyncio.Queue[bytes]  # 原始 PCM 片段 (16kHz, 16bit, mono)
stt_queue:        asyncio.Queue[bytes]  # VAD 判定 eos 后的完整音频段
token_queue:      asyncio.Queue[str]   # LLM 输出的 token 文本
audio_out_queue:  asyncio.Queue[bytes]  # TTS 返回的 PCM 音频段 (24kHz, 16bit, mono)
```

没有帧类型系统，只有 `bytes` 和 `str`。每个 Queue 设 `maxsize` 防 OOM。

### 3.2 各模块关键接口

```python
# vad.py - 轻量 VAD 封装
class SpeakerDetector:
    def __init__(self, stop_secs: float = 0.6, start_secs: float = 0.1,
                 min_volume: float = 0.01):
        ...

    async def process(self, audio_chunk: bytes) -> str:
        """
        喂入音频片段，返回当前状态:
          'speaking'  - 用户正在说话
          'silence'   - 短暂静音，还不确定是否结束
          'speech_end' - 静音超过 stop_secs，判定说话结束
        """
        ...

    def get_audio_buffer(self) -> bytes:
        """取出累积的完整音频段"""
        ...

    def reset(self) -> None:
        """新一轮 VAD 检测前重置缓冲区"""
        ...


# stt.py - faster-whisper 封装
class WhisperSTT:
    def __init__(self, model_size: str = "small", device: str = "cpu"):
        ...

    async def transcribe(self, audio: bytes, language: str = "zh") -> str:
        """完整音频段 → 转写文本，在线程池中运行以避免阻塞事件循环"""
        ...


# agent.py - LangGraph agent（从 main.py 抽离，逻辑不变）
async def run_llm(messages: list, config: dict,
                  cancel_event: asyncio.Event) -> AsyncIterator[str]:
    """
    LangGraph agent 流式调用 vLLM，逐个 token yield。
    每次 yield 前检查 cancel_event，被打断时提前终止。
    """
    ...


# sentence_splitter.py - FastSentenceAggregator 纯函数版
def find_split_point(text: str) -> tuple[str, str]:
    """
    在最近的标点处切分。
    返回 (前半句, 剩余文本)。
    没找到切分点返回 (text, '')。
    """
    ...


# tts_client.py - TTS HTTP 客户端
class TTSClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        ...

    async def stream_synthesize(self, text: str, voice: str = "Serena",
                                cancel_event: asyncio.Event) -> AsyncIterator[bytes]:
        """
        调用 Qwen TTS API，流式返回 PCM 字节 (24kHz)。
        cancel_event 被设置时取消 HTTP 请求。
        """
        ...


# config_manager.py - 基本不动
# openai_server_new.py - 不动，TTS 子进程
# index.html - 不动，开发测试用
```

### 3.3 main.py 核心编排

```python
app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"{websocket.client.host}:{websocket.client.port}"
    await run_pipeline(websocket, session_id)


async def run_pipeline(websocket: WebSocket, session_id: str):
    audio_queue = asyncio.Queue(maxsize=100)
    stt_queue = asyncio.Queue(maxsize=10)
    token_queue = asyncio.Queue(maxsize=50)
    audio_out_queue = asyncio.Queue(maxsize=100)
    interrupt_event = asyncio.Event()

    vad = SpeakerDetector()
    stt = WhisperSTT()
    agent, config = create_agent(session_id)
    tts = TTSClient()

    # 跟踪状态，用于打断判断
    state = {"tts_playing": False, "llm_generating": False}

    async def audio_receiver():
        """Task 1: WebSocket → audio_queue"""
        while True:
            data = await websocket.receive_bytes()
            await audio_queue.put(data)

    async def vad_loop():
        """Task 2: audio_queue → VAD → stt_queue，含打断逻辑"""
        while True:
            chunk = await audio_queue.get()
            status = await vad.process(chunk)

            if status == 'speaking' and (state["tts_playing"] or state["llm_generating"]):
                # 打断！
                interrupt_event.set()
                audio_out_queue.clear()
                # 清空 TTS/LLM 正在进行的工作，等新语音输入
                vad.reset()
                vad.fast_forward(chunk)  # 把当前 chunk 作为新语音的起点

            elif status == 'speech_end':
                audio_segment = vad.get_audio_buffer()
                if audio_segment:
                    await stt_queue.put(audio_segment)
                vad.reset()

    async def llm_loop():
        """Task 3: stt_queue → LangGraph → token_queue"""
        while True:
            audio_segment = await stt_queue.get()
            text = await stt.transcribe(audio_segment)
            if text.strip():
                state["llm_generating"] = True
                partial_response = ""
                inputs = {"messages": [HumanMessage(content=text)]}
                try:
                    async for chunk, _ in agent.astream(
                        inputs, config=config, stream_mode="messages"
                    ):
                        if interrupt_event.is_set():
                            break  # 被打断，停止生成
                        if chunk.content and isinstance(chunk.content, str):
                            partial_response += chunk.content
                            await token_queue.put(chunk.content)
                finally:
                    state["llm_generating"] = False
                    # ★ 将打断前的部分输出保存到 checkpoint
                    if partial_response:
                        agent.update_state(
                            config,
                            {"messages": [AIMessage(content=partial_response)]}
                        )
                    interrupt_event.clear()

    async def tts_loop():
        """Task 4: token_queue → 断句 → TTS → audio_out_queue"""
        buffer = ""
        while True:
            token = await token_queue.get()
            # 如果已被打断，丢弃队列中的残余 token
            if interrupt_event.is_set():
                buffer = ""
                continue
            buffer += token
            sentence, remainder = find_split_point(buffer)
            if sentence:
                state["tts_playing"] = True
                try:
                    async for pcm_chunk in tts.stream_synthesize(
                        sentence, cancel_event=interrupt_event
                    ):
                        if interrupt_event.is_set():
                            break  # 被打断，停止合成
                        await audio_out_queue.put(pcm_chunk)
                finally:
                    state["tts_playing"] = False
                buffer = remainder

    async def audio_sender():
        """Task 5: audio_out_queue → WebSocket"""
        while True:
            pcm_chunk = await audio_out_queue.get()
            await websocket.send_bytes(pcm_chunk)

    try:
        await asyncio.gather(
            audio_receiver(),
            vad_loop(),
            llm_loop(),
            tts_loop(),
            audio_sender(),
        )
    except WebSocketDisconnect:
        ...
    finally:
        # 保存用户画像
        current_state = agent.get_state(config)
        memory_messages = current_state.values.get("messages", [])
        if memory_messages:
            await save_user_info(model, config, memory_messages)
```

### 3.4 文件结构

```
├── main.py                # FastAPI + WebSocket + 管线编排
├── vad.py                 # SileroVAD 封装
├── stt.py                 # faster-whisper 封装
├── agent.py               # LangGraph agent（从 main.py 抽离）
├── sentence_splitter.py   # FastSentenceAggregator 纯函数版
├── tts_client.py          # Qwen TTS API 异步客户端
├── config_manager.py      # 不动
├── openai_server_new.py   # 不动，TTS 独立服务
├── start.sh               # 更新：并行等待 + 健康检查
├── Dockerfile             # 更新：Ollama → vLLM
├── index.html             # 不动，开发测试
├── config/
│   ├── persona.json
│   ├── teaching_style.json
│   └── user_1.json
└── requirements.txt       # 更新依赖
```

---

## 4. 错误处理

### 4.1 错误分类与策略

| 错误类型 | 处理方式 |
|---|---|
| vLLM 调用超时 | 最多重试 2 次，仍失败 → 日志记录，跳过当前轮 |
| TTS 调用超时 | 跳过当前句子，丢弃队列，继续下一句 |
| STT 转写失败 | 忽略该段音频，继续下一轮 VAD |
| WebSocket 断开 | 正常清理：保存用户画像 → 释放资源 |
| 模型服务崩溃 | 主控健康检查发现不可达后主动退出，Docker 自动重启 |
| Queue 满 (maxsize) | `put_nowait` + `QueueFull` catch，丢弃旧数据防 OOM |
| asyncio Task 崩溃 | `gather` 默认传播异常，触发全体取消和优雅关闭 |

**核心原则**：单用户对话场景，宁可丢一段也不全局崩溃。

### 4.2 优雅关闭流程

```
客户端断开 / 异常
  → 各 Task 收到 CancelledError
  → tts_loop / llm_loop 处理中的请求完成或超时取消
  → llm_loop 最后一轮调 save_user_info 更新用户画像
  → 清理 asyncio Task 树
  → 释放 STT / Agent / TTS 客户端资源
  → WebSocket 连接关闭
```

---

## 5. 容器部署

### 5.1 启动流程

```
容器启动
  │
  ├─ 并行启动 vLLM (后台，监听 8001)
  │   模型：qwen2.5-3b-instruct
  │
  ├─ 并行启动 Qwen TTS (后台，监听 8000)
  │
  ├─ 并行健康检查轮询（不等固定秒数）
  │   until curl http://localhost:8001/health; do sleep 2; done
  │   until curl http://localhost:8000/health; do sleep 2; done
  │
  └─ 启动 main.py (前台，监听 8080)
     容器存活 = main.py 进程存活
     main.py 退出 → 容器退出 → PAI-EAS 自动重启
```

### 5.2 Dockerfile 核心变更

| | 现在 | 重构后 |
|---|---|---|
| 基础镜像 | pytorch 2.1.2-cuda11.8 | pytorch 2.6+-cuda12.x（vLLM 需要） |
| LLM 安装 | `curl ollama.com/install.sh` | `pip install vllm` |
| 模型准备 | `ollama pull qwen2.5:3b` | 模型文件挂载或预下载 |
| TTS 模型 | `FasterQwen3TTS.from_pretrained()` | 不动 |
| 启动脚本 | 顺序 sleep | 并行健康检查 |

### 5.3 start.sh

```bash
#!/bin/bash
set -e

# 1. 并行启动 LLM 和 TTS
echo "启动 vLLM..."
vllm serve qwen2.5-3b-instruct --port 8001 --host 0.0.0.0 &

echo "启动 TTS 服务..."
python /app/openai_server_new.py &

# 2. 并行等待就绪
echo "等待 LLM 就绪..."
until curl -sf http://localhost:8001/health > /dev/null 2>&1; do
    sleep 2
done
echo "LLM 就绪 (端口 8001)"

echo "等待 TTS 就绪..."
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    sleep 2
done
echo "TTS 就绪 (端口 8000)"

# 3. 启动主控（前台，容器存活依赖此进程）
echo "启动主控服务..."
exec python /app/main.py
```

### 5.4 端口与健康检查

| 进程 | 端口 | 用途 | 健康检查 |
|---|---|---|---|
| vLLM | 8001 | LLM 推理 | `GET /health` (vLLM 内置) |
| Qwen TTS | 8000 | 语音合成 | `GET /health` (已有) |
| main | 8080 | WebSocket 主控 | `GET /` (FastAPI 默认) |

PAI-EAS 配置端口映射 `8080:8080`，负载均衡打到主控。

---

## 6. LLM 调用迁移：Ollama → vLLM

```python
# 现在 (Ollama)
model = init_chat_model(
    model="qwen2.5:3b-instruct",
    model_provider="ollama",
)

# 重构后 (vLLM 兼容 OpenAI API)
model = init_chat_model(
    model="qwen2.5-3b-instruct",
    model_provider="openai",
    base_url="http://localhost:8001/v1",
    temperature=0.7,
)
```

vLLM 默认提供 OpenAI 兼容 API，LangChain 的 `init_chat_model` 无需改接口。
