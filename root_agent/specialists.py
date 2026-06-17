"""Specialist agent adapters for the Root Agent."""

from __future__ import annotations

import asyncio
import importlib
import json
import re
from dataclasses import dataclass
from typing import Any

from google.adk.runners import InMemoryRunner
from google.genai import types

from .config import USER_ID_DEFAULT


@dataclass(slots=True)
class SpecialistResult:
    agent_name: str
    text: str
    payload: dict[str, Any]


SPECIALIST_MODULES = {
    "investment_research_agent": "investment_agent.agent",
    "investor_research_agent": "investor_agent.agent",
    "graph_database_agent": "graph_db_agent.agent",
}


async def invoke_specialist(
    agent_name: str,
    query_text: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    lessons: str = "",
) -> SpecialistResult:
    module_path = SPECIALIST_MODULES[agent_name]
    return await asyncio.to_thread(
        _invoke_specialist_sync,
        module_path,
        agent_name,
        query_text,
        user_id or USER_ID_DEFAULT,
        session_id or user_id or USER_ID_DEFAULT,
        lessons,
    )


def _invoke_specialist_sync(
    module_path: str,
    agent_name: str,
    query_text: str,
    user_id: str,
    session_id: str,
    lessons: str,
) -> SpecialistResult:
    module = importlib.import_module(module_path)
    runner = InMemoryRunner(agent=module.root_agent, app_name=module.APP_NAME)

    async def _run() -> SpecialistResult:
        session = await runner.session_service.create_session(
            app_name=module.APP_NAME,
            user_id=user_id,
        )
        prompt = _compose_prompt(query_text, lessons, session_id)
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        chunks: list[str] = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=message,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        chunks.append(part.text)
        text = "\n".join(chunks).strip()
        payload = _extract_payload(text) or {}
        return SpecialistResult(agent_name=agent_name, text=text, payload=payload)

    return asyncio.run(_run())


def _compose_prompt(query_text: str, lessons: str, session_id: str) -> str:
    segments = [
        f"Root orchestrator session: {session_id}",
        f"User query: {query_text}",
    ]
    if lessons.strip():
        segments.append("Lessons learned:\n" + lessons.strip())
    return "\n\n".join(segments)


def _extract_payload(text: str) -> dict[str, Any] | None:
    matches = re.findall(
        r"```json\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
