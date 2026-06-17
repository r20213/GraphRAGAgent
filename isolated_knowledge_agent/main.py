"""Minimal CLI runner for the autonomous standalone Knowledge Agent."""

from __future__ import annotations

import argparse
import json
import logging

from dotenv import load_dotenv

from .agent import KnowledgeAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone Knowledge Agent.")
    parser.add_argument("--query", required=True, help="Natural language question.")
    parser.add_argument("--entity", required=True, help="Target entity text.")
    return parser


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    args = build_parser().parse_args()
    agent = KnowledgeAgent()

    try:
        result = agent.run(user_query=args.query, target_entity=args.entity)
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "metrics": result.metrics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        agent.close()


if __name__ == "__main__":
    main()
