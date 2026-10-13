FROM python:3.11-slim-bookworm AS voxcpm-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL --retry 3 https://codeload.github.com/tc-mb/llama.cpp-omni/tar.gz/88bd37eb671f67cf8d747140ed100231756e0bc3 | tar -xz --strip-components=1
COPY scripts/configure_voxcpm.py /tmp/configure_voxcpm.py
RUN python /tmp/configure_voxcpm.py /src \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_CPU_ALL_VARIANTS=ON -DGGML_BACKEND_DL=ON -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
    && cmake --build build --target voxcpm2-cli --parallel 2 \
    && mkdir -p /native/bin \
    && cp build/bin/voxcpm2-cli build/bin/*.so* /native/bin/

FROM python:3.11-slim-bookworm AS base
LABEL org.opencontainers.image.title="Sal0 Voz" org.opencontainers.image.source="https://github.com/Sal0-Apps/Sal0-Voz"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng libsndfile1 libgomp1 sox gosu ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m venv /opt/engines/whisper && /opt/engines/whisper/bin/pip install --no-cache-dir faster-whisper==1.1.1 requests==2.32.3
RUN python -m venv /opt/engines/qwen && /opt/engines/qwen/bin/pip install --no-cache-dir torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu && /opt/engines/qwen/bin/pip install --no-cache-dir qwen-tts==0.1.1 soundfile==0.13.1 psutil==7.0.0
COPY requirements-chatterbox.txt ./
RUN python -m venv /opt/engines/chatterbox \
    && /opt/engines/chatterbox/bin/pip install --no-cache-dir torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && /opt/engines/chatterbox/bin/pip install --no-cache-dir -r requirements-chatterbox.txt \
    && /opt/engines/chatterbox/bin/pip install --no-cache-dir --no-deps --force-reinstall https://codeload.github.com/resemble-ai/chatterbox/tar.gz/5de7a54aa4e5e2baadb0182dde554908b48b85c2
RUN pip install --no-cache-dir huggingface-hub==0.36.0 && useradd --uid 1000 --create-home sal0
COPY requirements-omnivoice.txt ./
RUN python -m venv /opt/engines/omnivoice \
    && /opt/engines/omnivoice/bin/pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
    && /opt/engines/omnivoice/bin/pip install --no-cache-dir -r requirements-omnivoice.txt
COPY --from=voxcpm-build /native /opt/engines/voxcpm
# The shared runner imports memory/process helpers inside the ASR venv too.
# Keep this small dependency layer after existing runtimes to reuse their cache.
RUN /opt/engines/whisper/bin/python -m pip install --no-cache-dir psutil==7.0.0
# Model weights are downloaded by the running app into the persistent /data volume.
# Keep runtime dependencies before app/version changes so updates reuse their layers.
COPY app ./app
COPY scripts ./scripts
COPY MANUAL.md README.md THIRD_PARTY_NOTICES.md ./
COPY licenses ./licenses
RUN chmod +x scripts/entrypoint.sh
ENV SAL0_AUTO_DOWNLOAD_MODELS=1 SAL0_DATA=/data SAL0_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 HF_HOME=/data/models/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 GRADIO_ANALYTICS_ENABLED=False DO_NOT_TRACK=1 PYANNOTE_METRICS_ENABLED=0 SAL0_ENGINES=/opt/engines
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health',timeout=5)"
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","7860","--workers","1"]
LABEL org.opencontainers.image.version="0.4.1"
