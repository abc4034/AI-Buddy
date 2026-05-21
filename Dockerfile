# 建议使用 PyTorch 官方镜像作为基础，自带 CUDA 和 CUDNN
FROM pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime

# 设置工作目录
WORKDIR /app

# 安装基础工具包
RUN apt-get update && apt-get install -y curl ffmpeg libsm6 libxext6 gcc && rm -rf /var/lib/apt/lists/*

# 安装 Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# 将代码复制进镜像
COPY . /app

# 安装 Python 依赖
RUN pip install -r requirements.txt --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple

# 设置国内 HuggingFace 镜像源（加快预下载 TTS 模型的速度）
ENV HF_ENDPOINT=https://hf-mirror.com

# 预先拉取 Ollama 模型和 TTS 模型打包入镜像
# 先启动 ollama，拉取模型后再关闭；运行一次 tts 代码触发 huggingface 缓存下载
RUN nohup ollama serve & \
    sleep 5 && \
    ollama pull qwen2.5:3b-instruct && \
    python -c "from faster_qwen3_tts import FasterQwen3TTS; FasterQwen3TTS.from_pretrained('Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice')" && \
    pkill ollama

# 赋予启动脚本执行权限
RUN chmod +x /app/start.sh

# 暴露给 PAI-EAS 的端口
EXPOSE 8080

# 容器启动命令
CMD ["/app/start.sh"]