# AI Buddy — Real-time Voice Conversation Agent

A real-time speech-to-speech AI English tutor powered by LangGraph, Pipecat, and vLLM.

## Architecture

```
Browser Microphone → WebSocket → Whisper STT → LangGraph Agent (vLLM) → Qwen3 TTS → WebSocket → Browser Speaker
```

| Service | Port | Description |
|---------|------|-------------|
| vLLM | 8001 | Qwen2.5-3B-Instruct (OpenAI-compatible API) |
| TTS | 8000 | Qwen3-TTS-0.6B-CustomVoice |
| Main | 8002 | FastAPI + Pipecat Pipeline + WebSocket |

## Project Structure

```
├── main.py                    # FastAPI app, WebSocket endpoint, Pipecat pipeline, LangGraph agent
├── openai_server_new.py       # TTS API server (Qwen3 CustomVoice)
├── config_manager.py          # Persona, teaching style, user memory management
├── FastSentenceAggregator.py  # Sentence-aware TTS buffering (punctuation triggers synthesis)
├── start.sh                   # Container entrypoint (vLLM → TTS → Main)
├── index.html                 # Browser-based audio capture/playback frontend
├── config/
│   ├── persona.json           # AI character definition
│   ├── teaching_style.json    # Teaching methodology
│   └── user_1.json            # Per-user profile/memory
├── Dockerfile                 # Container image build
└── requirements.txt           # Python dependencies
```

## Local Development

```bash
# 1. Start Ollama (local only, replaced by vLLM in production)
ollama serve

# 2. Start TTS server
python openai_server_new.py

# 3. Start main service
python main.py

# 4. Open http://localhost:8002
```

## Production Deployment (Alibaba Cloud PAI-EAS)

1. Create a DSW instance with image `pytorch:2.6.0-gpu-py311-cu124-ubuntu22.04-accl`
2. Install dependencies: `pip install -r requirements.txt`
3. Pre-download NLTK data: `python -c "import nltk; nltk.download('punkt_tab')"`
4. Upload models to OSS and mount at `/mnt/data/`
5. Use DSW "Create Image" to snapshot the environment
6. Deploy via PAI-EAS with the ACR image + start.sh as entrypoint

## Configuration

- **GPU**: 24GB+ VRAM recommended (vLLM: 50% via `--gpu-memory-utilization 0.5`, TTS: ~1.2GB, Whisper: ~0.5GB)
- **Environment**: Python 3.11, PyTorch 2.6.0, CUDA 12.4
