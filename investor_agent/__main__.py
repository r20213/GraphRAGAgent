"""Local runtime entry point for the Investor Research Agent.

Two modes are supported:

* ``python -m investor_agent`` (default) — interactive REPL backed by an
  in-memory ADK runner; handy for smoke-testing tool wiring without A2A.
* ``python -m investor_agent --a2a`` — serves the A2A ASGI app with uvicorn,
  mirroring the Cloud Run deployment locally.
"""

from __future__ import annotations

import asyncio
import os
import sys

from .agent import APP_NAME, root_agent


async def _run_repl() -> None:
    """Drive the agent via an in-memory runner from the terminal."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    user_id = os.environ.get("ADK_USER_ID", "local-analyst")
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=user_id
    )

    print("Investor Research Agent — local test loop.")
    print("Type a research question, or 'exit' / Ctrl-D to quit.\n")

    while True:
        try:
            prompt = input("you> ").strip()
        except EOFError:
            print()
            break
        if prompt.lower() in {"exit", "quit"}:
            break
        if not prompt:
            continue

        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=message,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        print(f"\nagent> {part.text}\n")


def _serve_a2a() -> None:
    """Serve the A2A ASGI app with uvicorn (local mirror of Cloud Run)."""
    import uvicorn

    host = os.environ.get("A2A_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("A2A_PORT", "8080")))
    uvicorn.run("investor_agent.a2a:a2a_app", host=host, port=port)


def main() -> None:
    if "--a2a" in sys.argv[1:]:
        _serve_a2a()
        return
    try:
        asyncio.run(_run_repl())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
