FROM python:3.11-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng libsndfile1 libgomp1 sox gosu ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m venv /opt/engines/whisper && /opt/engines/whisper/bin/pip install --no-cache-dir faster-whisper==1.1.1 requests==2.32.3
RUN python -m venv /opt/engines/qwen && /opt/engines/qwen/bin/pip install --no-cache-dir torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu && /opt/engines/qwen/bin/pip install --no-cache-dir qwen-tts==0.1.1 soundfile==0.13.1
RUN pip install --no-cache-dir huggingface-hub==0.36.0 && useradd --uid 1000 --create-home sal0
COPY app ./app
COPY scripts ./scripts
COPY MANUAL.md README.md ./
RUN chmod +x scripts/entrypoint.sh
ENV SAL0_AUTO_DOWNLOAD_MODELS=1 SAL0_DATA=/data SAL0_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 HF_HOME=/data/models/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 PYANNOTE_METRICS_ENABLED=0 SAL0_ENGINES=/opt/engines
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health',timeout=5)"
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","7860","--workers","1"]
