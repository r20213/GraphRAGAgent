"""ADK wrapper for the standalone autonomous KnowledgeAgent."""

from __future__ import annotations

import json
import os

from google.adk import Agent

from .agent import KnowledgeAgent

APP_NAME = os.environ.get("ADK_APP_NAME", "isolated_knowledge_agent_app")
AGENT_MODEL = os.environ.get("ADK_MODEL", "gemini-2.0-flash")

SYSTEM_INSTRUCTION = """\
You are the ADK interface for the autonomous KnowledgeAgent.

For each request:
1. Extract the natural-language user query.
2. Extract a target entity string.
3. Call the tool `run_knowledge_agent` exactly once.
4. Return the tool result as the final output.

Do not invent facts outside the tool output.
"""


def run_knowledge_agent(user_query: str, target_entity: str) -> str:
    """Execute the standalone KnowledgeAgent and return JSON output."""
    agent = KnowledgeAgent()
    try:
        result = agent.run(user_query=user_query, target_entity=target_entity)
        return json.dumps(
            {
                "answer": result.answer,
                "metrics": result.metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
    finally:
        agent.close()


def build_agent() -> Agent:
    """Construct ADK agent surface that delegates to KnowledgeAgent."""
    return Agent(
        name="isolated_knowledge_agent",
        model=AGENT_MODEL,
        description=(
            "Autonomous knowledge agent wrapper that runs schema-agnostic "
            "graph pruning + Milvus contextual anchoring and returns answer "
            "with execution metrics."
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[run_knowledge_agent],
    )


root_agent = build_agent()
