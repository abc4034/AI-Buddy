#!/bin/bash

# 1. 启动 Ollama 服务在后台
echo "启动 Ollama..."
ollama serve > /dev/null 2>&1 &
sleep 5 # 等待 ollama 启动

# 2. 启动 TTS 服务在后台
echo "启动 TTS 服务..."
python openai_server_new.py > /app/tts.log 2>&1 &
sleep 10 # 等待 TTS 模型加载入显存

# 3. 启动主干程序在前台（阻断式，EAS 监控该进程）
echo "启动 WebSocket 主控服务..."
python main.py