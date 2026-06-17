# syntax=docker/dockerfile:1
#
# Cloud Run image for the Root Agent orchestrator.
#
# Build from the repository root so the specialist agent packages and the MCP
# server are available in the image:
#
#     docker build -f root_agent/Dockerfile -t root-agent .

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY root_agent/requirements.txt ./requirements.txt
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    PYTHONPATH=/app \
    ROOT_AGENT_HOST=0.0.0.0 \
    ROOT_AGENT_PORT=8080

COPY --from=builder /install /usr/local

WORKDIR /app

COPY root_agent/ ./root_agent/
COPY investment_agent/ ./investment_agent/
COPY investor_agent/ ./investor_agent/
COPY graph_db_agent/ ./graph_db_agent/
COPY mcp_server/ ./mcp_server/
COPY utils/ ./utils/

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD exec uvicorn root_agent.a2a:a2a_app --host 0.0.0.0 --port "${PORT}"