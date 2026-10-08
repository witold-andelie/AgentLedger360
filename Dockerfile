# syntax=docker/dockerfile:1
# Same two-stage pattern as the EuroGoal project: build React, then serve it from FastAPI.

# ─── Stage 1: build the React (Vite) frontend ─────────────
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build          # -> /app/frontend/dist

# ─── Stage 2: FastAPI (Python 3.13; code is also tested on 3.11) ─
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AL_FRONTEND_DIST=/app/frontend/dist \
    AL_VAR_DIR=/app/var
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install ".[ml,agent]"
COPY --from=frontend /app/frontend/dist /app/frontend/dist

EXPOSE 8000
# Render injects $PORT; default 8000 for `docker run`. SQLite lives in /app/var (ephemeral on Render free).
CMD ["sh", "-c", "uvicorn agentledger.server:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
