"""Root Agent orchestrator for specialized-agent-first routing."""

from __future__ import annotations

from google.adk import Agent

from .config import AGENT_MODEL, APP_NAME
from .memory import RootMemoryStore
from .routing import classify_query, render_markdown, should_save_memory
from .specialists import invoke_specialist

MEMORY = RootMemoryStore()

SYSTEM_INSTRUCTION = """\
You are the Root Agent, the orchestration layer for a multi-agent GraphRAG system.

Your operating rules are strict:
1. Specialized agents first, graph fallback last.
2. Before solving any substantive request, call the lesson retrieval tool so
   relevant historical corrections and successful query paths are injected into
   the context you use next.
3. Route high-confidence research questions to the Investment Research Agent,
   investor / portfolio-specific questions to the Investor Research Agent, and
   structural or dynamic traversal work to the Graph Database Agent.
4. Do not surface raw JSON unless it is needed for downstream machine parsing.
   Prefer clean Markdown tables or short explanatory text.
5. If the request is conversational fluff or a session-summary request, answer
   directly and do not write it to long-term memory.
6. When a specialist run succeeds or a correction / alias mapping / multi-agent
   track is discovered, the tool layer will queue the event for background
   ingestion; do not duplicate that work in your response.

When you delegate, preserve the user's original wording, the current session id,
and any lessons learned from retrieval. If the first specialist is insufficient,
escalate in the configured order rather than guessing.
"""


async def get_lessons_learned(
    query_text: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Retrieve Neon lessons and format them for the next model step."""
    lessons = await MEMORY.search_lessons(query_text)
    if not lessons:
        return "No relevant lessons found."
    lines = ["Relevant lessons learned:"]
    for lesson in lessons:
        lines.append(
            "- route={route} intent={intent} similarity={similarity:.3f} :: {text}".format(
                route=lesson.route,
                intent=lesson.intent,
                similarity=lesson.similarity,
                text=lesson.assistant_text[:240].strip(),
            )
        )
    return "\n".join(lines)


async def route_and_execute(
    query_text: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Route to the best specialist, aggregate the result, and queue memory."""
    session_id = session_id or "root-session"
    user_id = user_id or "root-user"

    session_state = await MEMORY.load_session_state(session_id)
    session_state.setdefault("turns", [])

    plan = classify_query(query_text)
    if plan.is_fluff:
        reply = "I am ready when you are. Ask me a research or graph question."
        session_state["turns"].append({"user": query_text, "assistant": reply})
        await MEMORY.save_session_state(session_id, session_state)
        return reply
    if plan.is_summary:
        reply = (
            "I can summarize the current conversation, but I do not persist "
            "summary requests to long-term memory."
        )
        session_state["turns"].append({"user": query_text, "assistant": reply})
        await MEMORY.save_session_state(session_id, session_state)
        return reply

    lessons = await get_lessons_learned(query_text, session_id, user_id)
    route_order = _candidate_routes(plan.route)
    specialist_result = None

    for specialist_name in route_order:
        specialist_result = await invoke_specialist(
            specialist_name,
            query_text,
            user_id=user_id,
            session_id=session_id,
            lessons=lessons,
        )
        if specialist_result.text.strip():
            break

    if specialist_result is None:
        reply = "No specialist could be invoked for this request."
        session_state["turns"].append({"user": query_text, "assistant": reply})
        await MEMORY.save_session_state(session_id, session_state)
        return reply

    payload = specialist_result.payload or {}
    markdown = render_markdown(payload, specialist_result.text)
    save, reason = should_save_memory(
        specialist_result.agent_name,
        payload,
        query_text,
    )
    if save:
        event = MEMORY.build_event_payload(
            session_id=session_id,
            user_id=user_id,
            route=specialist_result.agent_name,
            intent=str(payload.get("intent", specialist_result.agent_name)),
            query_text=query_text,
            assistant_text=markdown,
            payload=payload or {"raw_text": specialist_result.text},
            metadata={
                "reason": reason,
                "notes": payload.get("notes", ""),
            },
        )
        await MEMORY.enqueue_memory_event(event)

    session_state["turns"].append(
        {
            "user": query_text,
            "assistant": markdown,
            "route": specialist_result.agent_name,
            "save": save,
            "reason": reason,
        }
    )
    session_state["turns"] = session_state["turns"][-20:]
    await MEMORY.save_session_state(session_id, session_state)
    return markdown


def _candidate_routes(primary: str) -> list[str]:
    if primary == "investment_research_agent":
        return [
            "investment_research_agent",
            "investor_research_agent",
            "graph_database_agent",
        ]
    if primary == "investor_research_agent":
        return [
            "investor_research_agent",
            "investment_research_agent",
            "graph_database_agent",
        ]
    return [
        "graph_database_agent",
        "investment_research_agent",
        "investor_research_agent",
    ]


def build_agent() -> Agent:
    """Construct the Root Agent with retrieval and orchestration tools."""
    return Agent(
        name="root_orchestrator_agent",
        model=AGENT_MODEL,
        description=(
            "Orchestrates the specialized research agents, injects lessons "
            "learned from Neon, and routes structural fallback work to the "
            "Graph Database Agent."
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[get_lessons_learned, route_and_execute],
    )


root_agent = build_agent()