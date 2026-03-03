# =============================================================================
# JalNetra - Edge-AI Water Quality Monitoring System
# Multi-stage Dockerfile for production deployment
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build React Dashboard
# ---------------------------------------------------------------------------
FROM node:22-alpine AS dashboard-builder

WORKDIR /app/dashboard

# Copy dependency manifests first for layer caching
COPY dashboard/package.json dashboard/package-lock.json* ./

# Install dependencies (ci for reproducible builds, fallback to install)
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund; \
    fi

# Copy dashboard source code
COPY dashboard/ ./

# Build the production bundle
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python Runtime (Production)
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS production

# Metadata
LABEL maintainer="JalNetra Team"
LABEL description="JalNetra Edge-AI Water Quality Monitoring System"
LABEL version="1.0.0"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JALNETRA_ENV=production \
    JALNETRA_DATA_DIR=/app/data \
    JALNETRA_MODEL_DIR=/app/models \
    JALNETRA_LOG_DIR=/app/logs

# Install system dependencies required by ML libraries and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libfontconfig1 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

# Copy and install Python dependencies (cached layer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN groupadd --gid 1000 jalnetra \
    && useradd --uid 1000 --gid jalnetra --shell /bin/bash --create-home jalnetra

# Create application directories with proper ownership
RUN mkdir -p /app/data /app/models /app/logs /app/static \
    && chown -R jalnetra:jalnetra /app

# Copy built dashboard from Stage 1
COPY --from=dashboard-builder --chown=jalnetra:jalnetra /app/dashboard/dist /app/static/dashboard

# Copy edge application code
COPY --chown=jalnetra:jalnetra edge/ /app/edge/

# Copy training scripts (for on-demand model training)
COPY --chown=jalnetra:jalnetra training/ /app/training/

# Copy trained model weights (if they exist at build time)
COPY --chown=jalnetra:jalnetra models/ /app/models/

# Copy project configuration
COPY --chown=jalnetra:jalnetra pyproject.toml /app/

# Switch to non-root user
USER jalnetra

# Expose the FastAPI application port
EXPOSE 8000

# Health check: verify the API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Use tini as init process for proper signal handling
ENTRYPOINT ["tini", "--"]

# Start the FastAPI application with uvicorn
CMD ["python", "-m", "uvicorn", "edge.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
