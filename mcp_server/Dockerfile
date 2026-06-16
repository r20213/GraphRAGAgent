# syntax=docker/dockerfile:1

# ---- Builder: install dependencies into an isolated prefix ----------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

# ---- Runtime: minimal image running as a non-root user --------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

# Copy installed dependencies from the builder stage.
COPY --from=builder /install /usr/local

WORKDIR /app
COPY mcp_server/ ./mcp_server/
COPY utils/ ./utils/

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe: performs a real MCP initialize handshake.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "/app/mcp_server/healthcheck.py"]

CMD ["python", "/app/mcp_server/server.py"]
