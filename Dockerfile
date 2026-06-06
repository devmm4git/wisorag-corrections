# ── WISO-AI — FastAPI Cloud Run Container ─────────────────────────────────
# Python 3.11 slim — matches project standard (CONTRIBUTING.md)
# Single Dockerfile for all environments (dev / uat / prod)

FROM python:3.11-slim

# Metadata
LABEL maintainer="rag-sp@mm4.me"
LABEL project="wiso-ai"
LABEL milestone="M3"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Cloud Run requires PORT env var — default 8080
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose port
EXPOSE 8080

# Health check — Cloud Load Balancer probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/ai/health || exit 1

# Start FastAPI with uvicorn
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 1"]