"""Configuration for the Root Agent orchestrator."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / "utils" / ".env")

APP_NAME = os.getenv("ADK_APP_NAME", "root_orchestrator_app")
AGENT_MODEL = os.getenv("ADK_MODEL", "gemini-2.0-flash")
USER_ID_DEFAULT = os.getenv("ADK_USER_ID", "root-orchestrator")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL", "")
MEMORY_QUEUE_NAME = os.getenv("AGENT_MEMORY_QUEUE", "agent_memory_queue")
MEMORY_QUEUE_MAX_LENGTH = int(os.getenv("AGENT_MEMORY_QUEUE_MAX_LENGTH", "5000"))
MEMORY_VECTOR_DIMENSION = int(os.getenv("AGENT_MEMORY_VECTOR_DIMENSION", "64"))
MEMORY_TOP_K = int(os.getenv("AGENT_MEMORY_TOP_K", "3"))
SESSION_TTL_SECONDS = int(os.getenv("AGENT_SESSION_TTL_SECONDS", "86400"))
SESSION_STATE_PREFIX = os.getenv("AGENT_SESSION_STATE_PREFIX", "root_agent:session")

ROOT_AGENT_HOST = os.getenv("ROOT_AGENT_HOST", "0.0.0.0")
ROOT_AGENT_PORT = int(os.getenv("ROOT_AGENT_PORT", os.getenv("PORT", "8080")))

INVESTMENT_AGENT_A2A_URL = os.getenv("INVESTMENT_AGENT_A2A_URL", "")
INVESTOR_AGENT_A2A_URL = os.getenv("INVESTOR_AGENT_A2A_URL", "")
GRAPH_DB_AGENT_A2A_URL = os.getenv("GRAPH_DB_AGENT_A2A_URL", "")

LESSONS_TABLE = os.getenv("ROOT_AGENT_MEMORY_TABLE", "root_agent_memory")
LESSONS_EMBEDDING_INDEX = os.getenv(
    "ROOT_AGENT_MEMORY_INDEX", "root_agent_memory_embedding_idx"
)