# GV Support AI website: the same backend and UI as the desktop app, served to browsers.
# Built by Render (render.yaml at the repo root) or Hugging Face Spaces (web/deploy_space.py).
FROM node:22-slim AS ui
WORKDIR /ui
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci --ignore-scripts
COPY desktop/ ./
RUN npx vite build

FROM python:3.12-slim
ARG LLAMA_TAG=b11385
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 user
WORKDIR /app
COPY backend/requirements.txt backend/requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt
# Same llama.cpp engine as the desktop installer, used when the site runs its own model (GV_CONFIG_LLM_PROVIDER=embedded).
ADD "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/llama-${LLAMA_TAG}-bin-ubuntu-x64.tar.gz" /tmp/llama.tgz
RUN tar xzf /tmp/llama.tgz && mv "llama-${LLAMA_TAG}" llama && rm /tmp/llama.tgz
COPY backend/app ./app
COPY --from=ui /ui/dist ./ui
ENV GV_WEB_MODE=1 GV_WEB_DIR=/app/ui GV_LLAMA_SERVER=/app/llama/llama-server GV_SUPPORT_DATA_DIR=/home/user/data \
    GV_CONFIG_SETUP_COMPLETED=true GV_CONFIG_AUTO_SYNC_MINUTES=240 GV_CONFIG_ALLOW_LOCAL_EXECUTION=false PYTHONUNBUFFERED=1
USER user
EXPOSE 7860
# Render sets PORT; Hugging Face uses 7860.
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips '*'"]
