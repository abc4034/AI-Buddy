#!/bin/bash
set -e

cd /app/langgraph_pipecat_demo_v0.0.4.5

echo "=== 启动 vLLM 服务 ==="
vllm serve /mnt/data/LLM_MODELS/Qwen2.5-3B-Instruct \
    --host 0.0.0.0 --port 8001 \
    --gpu-memory-utilization 0.5 \
    --max-model-len 4096 \
    > /dev/null 2>&1 &
until curl -s http://localhost:8001/health > /dev/null 2>&1; do
    echo "  等待 vLLM 就绪..."
    sleep 2
done
echo "  vLLM 已就绪"

echo "=== 启动 TTS 服务 ==="
python openai_server_new.py > /app/tts.log 2>&1 &
until curl -s http://localhost:8000/health > /dev/null 2>&1; do
    echo "  等待 TTS 就绪..."
    sleep 2
done
echo "  TTS 已就绪"

echo "=== 启动主控服务 ==="
exec python main.py
