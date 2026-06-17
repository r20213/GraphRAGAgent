"""Local runtime entry point for the Root Agent orchestrator."""

from __future__ import annotations

import asyncio
import os
import sys

from .agent import APP_NAME, root_agent


async def _run_repl() -> None:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    user_id = os.environ.get("ADK_USER_ID", "local-root-user")
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
    )

    print("Root Agent — local test loop.")
    print("Type a question, or 'exit' / Ctrl-D to quit.\n")

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
    import uvicorn

    host = os.environ.get("A2A_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("A2A_PORT", "8080")))
    uvicorn.run("root_agent.a2a:a2a_app", host=host, port=port)


def main() -> None:
    if "--worker" in sys.argv[1:]:
        from .worker import main as worker_main

        worker_main()
        return
    if "--a2a" in sys.argv[1:]:
        _serve_a2a()
        return
    try:
        asyncio.run(_run_repl())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()