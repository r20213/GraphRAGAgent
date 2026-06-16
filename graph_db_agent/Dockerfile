# syntax=docker/dockerfile:1
#
# Cloud Run image for the Graph Database Agent (Google ADK + A2A).
#
# IMPORTANT: build from the REPOSITORY ROOT so the agent's sibling packages
# (mcp_server/, utils/) are inside the build context:
#
#     docker build -f graph_db_agent/Dockerfile -t graph-db-agent .
#
# The container serves the A2A protocol on the Cloud Run-provided $PORT and, at
# request time, launches mcp_server/server.py as a stdio subprocess for tool
# execution — so both the ADK and MCP dependencies live in this single image.

# ---- Builder: install dependencies into an isolated prefix ----------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY graph_db_agent/requirements.txt ./requirements.txt
RUN pip install --prefix=/install -r requirements.txt

# ---- Runtime: minimal image running as a non-root user --------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    PYTHONPATH=/app \
    MCP_SERVER_PATH=/app/mcp_server/server.py \
    MCP_TRANSPORT=stdio \
    NEO4J_READ_ONLY=true

# Copy installed dependencies from the builder stage.
COPY --from=builder /install /usr/local

WORKDIR /app

# Application code: the agent package plus the MCP server and shared utils that
# the agent spawns and depends on at runtime.
COPY graph_db_agent/ ./graph_db_agent/
COPY mcp_server/ ./mcp_server/
COPY utils/ ./utils/

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Serve the A2A ASGI app. Shell form lets Cloud Run's $PORT expand at runtime;
# the agent card is published at /.well-known/agent-card.json. Neo4j credentials
# (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE) are injected at
# deploy time via Cloud Run env vars / Secret Manager — never baked into the image.
CMD exec uvicorn graph_db_agent.a2a:a2a_app --host 0.0.0.0 --port "${PORT}"
