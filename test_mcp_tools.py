"""CLI smoke-test client for the Neo4j GraphRAG MCP server.

Usage examples
--------------
# List all available tools:
    python test_mcp_tools.py --list

# Run a full-text search (default top_k=20):
    python test_mcp_tools.py --fts "Google"

# Run a full-text search with Lucene syntax and a custom result cap:
    python test_mcp_tools.py --fts "Apple~" --top-k 5

# Execute an arbitrary read-only Cypher query:
    python test_mcp_tools.py --cypher "MATCH (o:Organization) RETURN o.name LIMIT 5"

# Inspect the connected graph schema:
    python test_mcp_tools.py --schema

# Override the server URL (default: http://localhost:8000/mcp):
    python test_mcp_tools.py --url http://myserver:8000/mcp --fts "Microsoft"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import nest_asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

nest_asyncio.apply()

DEFAULT_URL = "http://localhost:8000/mcp"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Neo4j GraphRAG MCP server from the CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        metavar="URL",
        help=f"MCP server endpoint (default: {DEFAULT_URL}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all tools registered on the server.",
    )
    parser.add_argument(
        "--fts",
        metavar="QUERY",
        help=(
            "Run a full-text search via the global_entity_search index. "
            "Lucene syntax supported (e.g. 'Google OR Apple', 'Acme~')."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of FTS results to return (default: 20).",
    )
    parser.add_argument(
        "--cypher",
        metavar="CYPHER",
        help="Execute an arbitrary read-only Cypher query.",
    )
    parser.add_argument(
        "--params",
        metavar="JSON",
        default="{}",
        help="JSON object of Cypher parameters for --cypher (default: {}).",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the graph schema returned by get_neo4j_schema.",
    )
    return parser


def _pretty(result_text: str) -> str:
    """Try to pretty-print JSON; fall back to raw text."""
    try:
        parsed = json.loads(result_text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return result_text


async def _run(args: argparse.Namespace) -> int:
    exit_code = 0

    async with streamablehttp_client(args.url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ----------------------------------------------------------------
            # --list
            # ----------------------------------------------------------------
            if args.list:
                tools_response = await session.list_tools()
                tool_names = [t.name for t in tools_response.tools]
                print(f"Registered tools on {args.url}:")
                for name in tool_names:
                    print(f"  - {name}")
                print(f"\nTotal: {len(tool_names)} tool(s)")

            # ----------------------------------------------------------------
            # --fts
            # ----------------------------------------------------------------
            if args.fts:
                print(
                    f"\n[search_entities_fts] query={args.fts!r}, "
                    f"top_k={args.top_k}"
                )
                result = await session.call_tool(
                    "search_entities_fts",
                    {"query": args.fts, "top_k": args.top_k},
                )
                text = result.content[0].text if result.content else "(no content)"
                print(_pretty(text))

            # ----------------------------------------------------------------
            # --cypher
            # ----------------------------------------------------------------
            if args.cypher:
                try:
                    params = json.loads(args.params)
                except json.JSONDecodeError as exc:
                    print(
                        f"ERROR: --params is not valid JSON: {exc}",
                        file=sys.stderr,
                    )
                    return 1

                print(f"\n[run_graph_query] cypher={args.cypher!r}")
                result = await session.call_tool(
                    "run_graph_query",
                    {"cypher": args.cypher, "parameters": params},
                )
                text = result.content[0].text if result.content else "(no content)"
                print(_pretty(text))

            # ----------------------------------------------------------------
            # --schema
            # ----------------------------------------------------------------
            if args.schema:
                print("\n[get_neo4j_schema]")
                result = await session.call_tool("get_neo4j_schema", {})
                text = result.content[0].text if result.content else "(no content)"
                print(text)

            # Default: if no flags were given, just show tools
            if not any([args.list, args.fts, args.cypher, args.schema]):
                tools_response = await session.list_tools()
                tool_names = [t.name for t in tools_response.tools]
                print(
                    "No action specified. Available tools:\n  "
                    + "\n  ".join(tool_names)
                )
                print("\nUse --help for usage examples.")

    return exit_code


def main() -> int:
    args = _build_arg_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
