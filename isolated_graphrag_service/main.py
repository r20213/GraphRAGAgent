"""CLI entry point for the standalone LEGO-GraphRAG service."""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from .service import LegoGraphRAGService, ServiceConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the standalone dual-retrieval LEGO-GraphRAG service with a "
            "natural language query and a target entity."
        )
    )
    parser.add_argument("--query", required=True, help="Natural language question.")
    parser.add_argument("--entity", required=True, help="Target entity anchor text.")
    return parser


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    args = build_parser().parse_args()
    config = ServiceConfig.from_env()
    service = LegoGraphRAGService(config)

    try:
        answer = service.run(query=args.query, target_entity=args.entity)
        print(answer)
    finally:
        service.close()


if __name__ == "__main__":
    main()
