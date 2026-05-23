FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y curl ffmpeg gcc procps \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install -r requirements.txt --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/

RUN python -c "import nltk; nltk.download('punkt_tab')"

RUN chmod +x /app/start.sh

EXPOSE 8002

CMD ["/app/start.sh"]
