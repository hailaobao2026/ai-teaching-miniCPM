# syntax=docker/dockerfile:1

# ---------- Frontend build ----------
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Backend runtime ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MATH_COACH_DB_BACKEND=sqlite \
    MATH_COACH_SQLITE_PATH=/app/data/math-coach.db

WORKDIR /app

# System CA certs help when VLLM_OMNI_URL uses HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code only (see .dockerignore).
COPY app.py ./
COPY config ./config
COPY teaching ./teaching
COPY static ./static
COPY scripts ./scripts
COPY eval ./eval
COPY docs ./docs
COPY README.md requirements-gpu.txt ./
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Persistable auth store directory; mount a volume over /app/data in compose.
RUN mkdir -p /app/data \
    && chmod +x scripts/start_vllm_omni.sh scripts/install_vllm_omni.sh \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8089
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8089"]
