"""Minimal CLI runner for the autonomous standalone Knowledge Agent."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from .agent import KnowledgeAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone Knowledge Agent.")
    parser.add_argument("--query", help="Natural language question.")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Start interactive REPL mode.",
    )
    return parser


def main() -> None:
    local_env = Path(__file__).resolve().parent / ".env"
    load_dotenv(local_env)
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    args = build_parser().parse_args()
    agent = KnowledgeAgent()

    try:
        if args.repl:
            _run_repl(agent)
            return

        if not args.query:
            raise SystemExit("For one-shot mode, pass --query.")

        result = agent.run(user_query=args.query)
        print(_as_json(result.answer, result.metrics))
    finally:
        agent.close()


def _run_repl(agent: KnowledgeAgent) -> None:
    print("Knowledge Agent REPL")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            query = input("you> ").strip()
        except EOFError:
            print()
            break

        if query.lower() in {"exit", "quit"}:
            break
        if not query:
            continue

        result = agent.run(user_query=query)
        print()
        print("agent>", result.answer)
        print(_as_json(result.answer, result.metrics))
        print()


def _as_json(answer: str, metrics: dict) -> str:
    return json.dumps(
        {
            "answer": answer,
            "metrics": metrics,
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    main()
