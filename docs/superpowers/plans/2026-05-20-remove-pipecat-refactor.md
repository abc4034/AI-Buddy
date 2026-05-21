# Remove Pipecat & Refactor to asyncio Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Pipecat framework, replace Ollama with vLLM, implement pipeline using asyncio.Queue + 5 async Tasks.

**Architecture:** 5 asyncio Tasks connected by 4 asyncio.Queues, coordinated by 1 asyncio.Event for barge-in. Each module is a self-contained wrapper with no framework dependency.

**Tech Stack:** FastAPI + WebSocket, LangGraph (unchanged), faster-whisper, SileroVAD (torch.hub), vLLM (OpenAI-compatible), Qwen TTS (unchanged)

**Model paths:** 暂不改动，沿用原有 HuggingFace 模型 ID。重构完成后再迁移到 OSS。

---

### Task 1: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Remove pipecat, add new dependencies**

Replace `requirements.txt` content:

```
fastapi==0.135.2
faster_qwen3_tts==0.2.4
faster-whisper==1.1.1
langchain==1.2.13
langchain_core==1.2.23
langgraph==1.1.3
numpy==2.4.4
pydantic==2.12.5
pydub==0.25.1
python-dotenv==1.2.2
torch==2.6.0+cu124
typing_extensions==4.15.0
uvicorn==0.42.0
vllm>=0.8.0
httpx>=0.28.0
```

- [ ] **Step 2: Install new dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: remove pipecat_ai, add vllm, faster-whisper, httpx"
```

---

### Task 2: Create sentence_splitter.py

**Files:**
- Create: `sentence_splitter.py`

> Pure-function version of `FastSentenceAggregator`. No pipecat dependency. Input a growing text buffer, output (sentence, remainder) when punctuation is found.

- [ ] **Step 1: Write the module**

```python
import re

_PUNCTUATION_PATTERN = r"[.?!。？！,，、;；\n]+[\'\"\"\'\]\)]*\s*$"


def find_split_point(text: str) -> tuple[str, str]:
    """
    Find the nearest punctuation boundary in text and split there.

    Returns (sentence, remainder). If no split point is found, returns (text, "").
    """
    match = re.search(_PUNCTUATION_PATTERN, text)
    if match:
        pos = match.end()
        return text[:pos].strip(), text[pos:].lstrip()
    return text, ""


def has_punctuation(text: str) -> bool:
    """Check if text ends with a sentence-ending punctuation mark (any language)."""
    return bool(re.search(_PUNCTUATION_PATTERN, text.rstrip()))
```

- [ ] **Step 2: Verify import**

```bash
python -c "from sentence_splitter import find_split_point, has_punctuation; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add sentence_splitter.py
git commit -m "feat: add sentence_splitter — pure-function punctuation-based sentence boundary detection"
```

---

### Task 3: Create stt.py

**Files:**
- Create: `stt.py`

> Wraps faster-whisper. Runs the FULL blocking transcription (encode + decode) inside a thread pool. Converts raw 16kHz 16bit mono PCM bytes → text.

- [ ] **Step 1: Write the module**

```python
import asyncio

import numpy as np
from faster_whisper import WhisperModel


class WhisperSTT:
    def __init__(self, model_size: str = "small",
                 device: str = "cpu", compute_type: str = "int8",
                 language: str = "zh"):
        self._language = language
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe raw PCM bytes (16kHz, 16bit, mono) to text.
        Entire transcription (encode + decode) runs in a thread pool."""
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        loop = asyncio.get_event_loop()

        def _run():
            segments, _ = self._model.transcribe(audio_array, language=self._language)
            return [seg.text.strip() for seg in segments]

        texts = await loop.run_in_executor(None, _run)
        return " ".join(texts)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from stt import WhisperSTT; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add stt.py
git commit -m "feat: add WhisperSTT — faster-whisper wrapper, full thread-pool execution"
```

---

### Task 4: Create vad.py

**Files:**
- Create: `vad.py`

> Wraps SileroVAD via torch.hub. Accumulates audio during speech. Implements both start_secs (speech onset hysteresis) and stop_secs (silence threshold). Volume gate filters noise.

- [ ] **Step 1: Write the module**

```python
import time

import numpy as np
import torch


class SpeakerDetector:
    def __init__(self, stop_secs: float = 0.6, start_secs: float = 0.1,
                 min_volume: float = 0.01, sample_rate: int = 16000):
        self._stop_secs = stop_secs
        self._start_secs = start_secs
        self._min_volume = min_volume
        self._sample_rate = sample_rate

        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad"
        )

        self._audio_buffer: list[bytes] = []
        self._speaking = False
        self._speech_start: float | None = None  # first non-silence timestamp
        self._silence_start: float | None = None

        # Possible statuses: 'silence' | 'starting' | 'speaking' | 'speech_end'
        self._last_status: str = "silence"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, audio_chunk: bytes) -> str:
        """
        Feed a chunk of 16-bit PCM audio. Returns current status:
          'silence'    — user is not speaking
          'starting'   — user just started but start_secs not yet met
          'speaking'   — user is actively speaking
          'speech_end' — user finished speaking (silence > stop_secs)
        """
        chunk_tensor = self._to_tensor(audio_chunk)

        # Volume gate — treat as silence
        rms = float(torch.sqrt(torch.mean(chunk_tensor ** 2)))
        if rms < self._min_volume:
            return self._handle_silence()

        # VAD probability
        speech_prob = self._model(chunk_tensor, self._sample_rate).item()

        if speech_prob >= 0.5:
            return self._handle_speech(audio_chunk)
        else:
            return self._handle_silence()

    def get_audio_buffer(self) -> bytes:
        """Return accumulated audio and clear buffer."""
        result = b"".join(self._audio_buffer)
        self._audio_buffer.clear()
        return result

    def reset(self) -> None:
        """Reset state for a new detection cycle (keeps any buffered audio)."""
        self._speaking = False
        self._speech_start = None
        self._silence_start = None
        self._last_status = "silence"

    def fast_forward(self, audio_chunk: bytes) -> None:
        """Seed a new detection cycle with initial chunk (used after interruption)."""
        self.reset()
        self._audio_buffer.append(audio_chunk)
        self._speaking = True
        self._speech_start = time.monotonic()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_tensor(self, audio_bytes: bytes) -> torch.Tensor:
        arr = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return torch.from_numpy(arr.copy())

    def _handle_speech(self, audio_chunk: bytes) -> str:
        now = time.monotonic()

        if not self._speaking:
            if self._speech_start is None:
                self._speech_start = now
            if now - self._speech_start < self._start_secs:
                self._last_status = "starting"
                return "starting"

            self._speaking = True

        self._silence_start = None
        self._audio_buffer.append(audio_chunk)
        self._last_status = "speaking"
        return "speaking"

    def _handle_silence(self) -> str:
        if not self._speaking:
            self._last_status = "silence"
            return "silence"

        now = time.monotonic()
        if self._silence_start is None:
            self._silence_start = now
            self._last_status = "speaking"
            return "speaking"

        if now - self._silence_start >= self._stop_secs:
            self._speaking = False
            self._speech_start = None
            self._last_status = "speech_end"
            return "speech_end"

        self._last_status = "speaking"
        return "speaking"
```

- [ ] **Step 2: Verify import**

```bash
python -c "from vad import SpeakerDetector; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add vad.py
git commit -m "feat: add SpeakerDetector — SileroVAD via torch.hub, with start/stop hysteresis and volume gate"
```

---

### Task 5: Create tts_client.py

**Files:**
- Create: `tts_client.py`

> Async HTTP client for the Qwen TTS service (OpenAI-compatible API at localhost:8000). Streams PCM bytes. Respects cancel_event for barge-in. HTTP connection is closed on cancel (context manager exit).

- [ ] **Step 1: Write the module**

```python
import asyncio

import httpx


class TTSClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def stream_synthesize(self, text: str, voice: str = "Serena",
                                cancel_event: asyncio.Event | None = None):
        """Call Qwen TTS API and yield PCM bytes (24kHz, 16bit, mono) as they arrive."""
        if not self._client:
            raise RuntimeError("TTSClient not started")

        url = f"{self._base_url}/v1/audio/speech"
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "pcm",
        }

        async with self._client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if cancel_event and cancel_event.is_set():
                    break
                if chunk:
                    yield chunk
```

- [ ] **Step 2: Verify import**

```bash
python -c "from tts_client import TTSClient; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add tts_client.py
git commit -m "feat: add TTSClient — async HTTP streaming client for Qwen TTS API"
```

---

### Task 6: Create agent.py

**Files:**
- Create: `agent.py`

> Extract LangGraph agent creation and LLM invocation from main.py. Model provider switched from Ollama to vLLM (OpenAI-compatible). `OPENAI_API_KEY` set to dummy value for vLLM.

- [ ] **Step 1: Write the module**

```python
import operator
import os

from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

from config_manager import ConfigManager

os.environ.setdefault("OPENAI_API_KEY", "vllm-no-key-needed")


class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int


config_manager = ConfigManager()

model = init_chat_model(
    model="qwen2.5-3b-instruct",
    model_provider="openai",
    base_url="http://localhost:8001/v1",
    temperature=0.7,
)


async def llm_call(state: dict, config: RunnableConfig) -> dict:
    user_id = config["configurable"].get("user_id")
    user_memory = config_manager.get_user_memory(user_id)
    system_prompt = config_manager.build_system_prompt(user_memory)

    response = await model.ainvoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )
    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def create_agent() -> tuple[StateGraph, dict]:
    agent_builder = StateGraph(MessageState)
    agent_builder.add_node("llm_call", llm_call)
    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_edge("llm_call", END)
    checkpoint = InMemorySaver()
    agent = agent_builder.compile(checkpoint)
    return agent, checkpoint
```

- [ ] **Step 2: Verify import**

```bash
python -c "from agent import create_agent; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: extract agent — LangGraph agent, Ollama->vLLM, dummy API key"
```

---

### Task 7: Rewrite main.py

**Files:**
- Modify: `main.py`

> Replace the Pipecat Pipeline with 5 asyncio Tasks + 4 Queues + 1 Event. Remove all pipecat imports. Keep FastAPI + WebSocket + save_user_info logic. `UserInfo` defined directly in main.py. Queue.put uses `put_nowait` to avoid deadlock on full queues.

- [ ] **Step 1: Write the new main.py**

```python
import asyncio
from typing import Optional

import dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from langchain.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field

from agent import create_agent, model, config_manager
from stt import WhisperSTT
from vad import SpeakerDetector
from tts_client import TTSClient
from sentence_splitter import find_split_point


dotenv.load_dotenv()
app = FastAPI()


class UserInfo(BaseModel):
    name: Optional[str] = Field(default=None)
    hobbies: Optional[list[str]] = Field(default=None)
    english_level: Optional[str] = Field(default=None)
    current_goal: Optional[str] = Field(default=None)
    special_notes: Optional[str] = Field(default=None)


async def save_user_info(config: dict, memory: list) -> str:
    user_id = config["configurable"].get("user_id")
    user_old_info = config_manager.get_user_memory(user_id)
    update_prompt = (
        f"这是用户的画像：{user_old_info}\n"
        f"这是用户本次对话历史{memory}。\n"
        f"请根据以上对话历史更新用户画像，并只以JSON格式输出"
    )
    try:
        structured_model = model.with_structured_output(UserInfo)
        user_new_info = await structured_model.ainvoke(
            [HumanMessage(content=update_prompt)]
        )
        user_new_info_dict = user_new_info.model_dump(exclude_none=True)
        if user_new_info_dict:
            config_manager.update_user_memory(user_id, user_new_info_dict)
            return "保存用户信息成功"
        return "未提取到需要更新的信息"
    except Exception as e:
        return f"更新记忆时发生未知错误:{e}"


async def run_pipeline(websocket: WebSocket, session_id: str):
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    stt_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=10)
    token_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    audio_out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
    interrupt_event = asyncio.Event()

    vad = SpeakerDetector()
    stt = WhisperSTT()
    agent, config = create_agent()
    tts = TTSClient()
    await tts.start()

    state = {"tts_playing": False, "llm_generating": False}

    async def audio_receiver():
        """Task 1: WebSocket → audio_queue"""
        while True:
            data = await websocket.receive_bytes()
            try:
                audio_queue.put_nowait(data)
            except asyncio.QueueFull:
                pass  # drop chunk if consumer is slow

    async def vad_loop():
        """Task 2: audio_queue → VAD → stt_queue (with interruption)"""
        while True:
            chunk = await audio_queue.get()
            status = vad.process(chunk)

            if status == "speaking" and (state["tts_playing"] or state["llm_generating"]):
                # ---- BARGE-IN ----
                interrupt_event.set()
                while not audio_out_queue.empty():
                    audio_out_queue.get_nowait()
                vad.reset()
                vad.fast_forward(chunk)

            elif status == "speech_end":
                audio_segment = vad.get_audio_buffer()
                vad.reset()
                if audio_segment and len(audio_segment) > 800:  # >50ms at 16kHz 16bit
                    try:
                        stt_queue.put_nowait(audio_segment)
                    except asyncio.QueueFull:
                        pass

    async def llm_loop():
        """Task 3: stt_queue → LangGraph → token_queue"""
        while True:
            audio_segment = await stt_queue.get()
            text = await stt.transcribe(audio_segment)
            if not text.strip():
                continue

            state["llm_generating"] = True
            inputs = {"messages": [HumanMessage(content=text)]}
            partial_response = ""

            try:
                async for chunk, _ in agent.astream(
                    inputs, config=config, stream_mode="messages"
                ):
                    if interrupt_event.is_set():
                        break
                    content = chunk.content
                    if content and isinstance(content, str):
                        partial_response += content
                        try:
                            token_queue.put_nowait(content)
                        except asyncio.QueueFull:
                            pass
            finally:
                state["llm_generating"] = False
                if partial_response:
                    agent.update_state(
                        config,
                        {"messages": [AIMessage(content=partial_response)]}
                    )
                interrupt_event.clear()

    async def tts_loop():
        """Task 4: token_queue → split sentences → TTS → audio_out_queue"""
        buffer = ""
        while True:
            token = await token_queue.get()
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
                            break
                        try:
                            audio_out_queue.put_nowait(pcm_chunk)
                        except asyncio.QueueFull:
                            pass
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
        pass
    finally:
        await tts.stop()
        current_state = agent.get_state(config)
        memory_messages = current_state.values.get("messages", []) if current_state else []
        if memory_messages:
            result = await save_user_info(config, list(memory_messages))
            print(f"[{session_id}] 记忆更新结果: {result}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"{websocket.client.host}:{websocket.client.port}"
    await run_pipeline(websocket, session_id)


@app.get("/")
async def get():
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    print("启动 Web 语音服务...")
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('main.py').read()); print('Syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: rewrite main.py — asyncio.Queue pipeline replacing Pipecat"
```

---

### Task 8: Update start.sh

**Files:**
- Modify: `start.sh`

> Replace Ollama with vLLM. Add health-check polling. Models use HF IDs for now.

- [ ] **Step 1: Write new start.sh**

```bash
#!/bin/bash
set -e

echo "启动 vLLM..."
vllm serve Qwen/Qwen2.5-3B-Instruct --port 8001 --host 0.0.0.0 &

echo "启动 TTS 服务..."
python /app/openai_server_new.py &

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

echo "启动主控服务..."
exec python /app/main.py
```

- [ ] **Step 2: Commit**

```bash
git add start.sh
git commit -m "feat: update start.sh — vLLM from local path, health-check polling"
```

---

### Task 9: Update Dockerfile

**Files:**
- Modify: `Dockerfile`

> New base image for CUDA 12.x. Remove Ollama install. Keep TTS model HF pre-download. vLLM model downloads on first start.

- [ ] **Step 1: Write new Dockerfile**

```dockerfile
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y curl ffmpeg libsm6 libxext6 gcc && \
    rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install -r requirements.txt --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple

ENV HF_ENDPOINT=https://hf-mirror.com

# 预下载 TTS 模型
RUN python -c "from faster_qwen3_tts import FasterQwen3TTS; \
    FasterQwen3TTS.from_pretrained('Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice')"

RUN chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat: update Dockerfile — CUDA 12.4 base, no model downloads, OSS mount paths"
```

---

### Task 10: Integration test

**Files:**
- Create: `test_pipeline.py`

- [ ] **Step 1: Write integration smoke test**

```python
"""Smoke test — verifies all modules import and basic pipeline wiring."""
import pytest


def test_imports():
    from sentence_splitter import find_split_point, has_punctuation
    from stt import WhisperSTT
    from vad import SpeakerDetector
    from tts_client import TTSClient
    from agent import create_agent, model
    assert True


def test_split_punctuation():
    from sentence_splitter import find_split_point

    # Comma triggers split
    s, r = find_split_point("Hello, world")
    assert s == "Hello,"
    assert r == "world"

    # Period triggers split
    s, r = find_split_point("I am here. You are there")
    assert s == "I am here."
    assert r == "You are there"

    # Chinese punctuation
    s, r = find_split_point("你好，世界")
    assert s == "你好，"
    assert r == "世界"

    # No punctuation — returns full text as sentence
    s, r = find_split_point("Hello world")
    assert s == "Hello world"
    assert r == ""


def test_vad_init_and_reset():
    from vad import SpeakerDetector
    vad = SpeakerDetector()
    assert vad is not None

    # Reset on fresh detector should be safe
    vad.reset()
    assert vad._speaking is False

    # get_audio_buffer on empty buffer returns empty bytes
    assert vad.get_audio_buffer() == b""


def test_agent_creation():
    from agent import create_agent
    agent, checkpoint = create_agent()
    assert agent is not None
    assert checkpoint is not None


class TestInterruptionLogic:
    """Verify that update_state appends (via operator.add reducer), not replaces."""

    def test_update_state_preserves_prior_messages(self):
        from langchain.messages import AIMessage, HumanMessage
        from agent import create_agent

        agent, config = create_agent()

        # Simulate: a full assistant response was saved
        agent.update_state(
            config,
            {"messages": [AIMessage(content="Hello! How can I help?")]}
        )

        # Then a partial response from interruption
        agent.update_state(
            config,
            {"messages": [AIMessage(content="Well, let me think...")]}
        )

        state = agent.get_state(config)
        messages = state.values["messages"]
        assert len(messages) == 2
        assert messages[0].content == "Hello! How can I help?"
        assert messages[1].content == "Well, let me think..."
```

- [ ] **Step 2: Run tests**

```bash
pytest test_pipeline.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add test_pipeline.py
git commit -m "test: add integration smoke tests for pipeline modules"
```

---

### Completion Checklist

1. Start vLLM: `vllm serve Qwen/Qwen2.5-3B-Instruct --port 8001 --host 0.0.0.0`
2. Start TTS: `python openai_server_new.py`
3. Start main: `python main.py`
4. Open `http://localhost:8080` in browser
5. Click "连接并开始对话", speak, verify AI responds with audio
6. Verify interruption: speak while AI is talking, confirm it stops and listens
