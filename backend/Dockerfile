# 1. lépés: a React UI lefordítása (Vite) – a kész dist a backend static mappájába kerül.
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. lépés: közös image az api-nak és a worker-nek (a worker a Doclingot futtatja, az api a chatet + UI-t).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/models/hf

# - tesseract (hun, eng): OCR a szövegréteg nélküli PDF-oldalakra és a képek feliratára
# - libgl1, libglib2.0-0: OpenCV (a Docling képfeldolgozása)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-hun tesseract-ocr-eng \
        libgl1 libglib2.0-0 fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-s torch (GPU nincs): így a Docling nem húzza be a ~2,5 GB-os CUDA-s változatot
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY --from=ui /ui/dist ./static

EXPOSE 8000
