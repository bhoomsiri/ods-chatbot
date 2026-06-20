FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

COPY requirements.txt .
# Install CUDA (cu124) torch + torchvision first — the wheel bundles its own
# CUDA runtime libs, so a plain slim base + NVIDIA driver passed via
# `--gpus`/compose device reservation is enough (no nvidia/cuda base image).
# cu124 is forward-compatible with the host's CUDA 12.9 driver. The reranker
# and bge-m3 then run on GPU in fp16 automatically. For a CPU-only host, swap
# the index-url to .../whl/cpu.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
