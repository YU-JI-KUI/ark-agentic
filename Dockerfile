# Dockerfile for ark-agentic
# Multi-stage build for smaller image size

# ============ Frontend Build ============
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY src/ark_agentic/studio/frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY src/ark_agentic/studio/frontend/ ./
RUN npm run build

# ============ Python Build Stage ============
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=frontend /frontend/dist ./src/ark_agentic/studio/frontend/dist

# Create virtual environment and install dependencies
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache ".[server,jobs,postgres]"

# ============ Runtime Stage ============
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime dependencies for sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY --from=frontend /frontend/dist ./src/ark_agentic/studio/frontend/dist

# Create directories for persistence
# /data/memory contains SQLite .db files — use Docker named volumes (not bind mounts)
# to avoid WAL mode issues with cross-filesystem access.
RUN mkdir -p /data/sessions /data/memory

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8080 \
    SESSIONS_DIR=/data/sessions \
    MEMORY_DIR=/data/memory

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

# Run the API server
CMD ["ark-agentic-api"]
