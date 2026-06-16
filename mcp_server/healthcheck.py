"""Container healthcheck for the streamable-HTTP MCP server.

Performs a minimal JSON-RPC ``initialize`` handshake against the MCP endpoint
and exits 0 only if the server responds successfully. Used by the Docker
``HEALTHCHECK`` instruction and the CI smoke test.

Configured via the same env vars as the server: ``MCP_HOST`` / ``MCP_PORT``.
Note: inside the container we always probe ``127.0.0.1`` (the server may bind
``0.0.0.0``, which is not a connectable address).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(os.getenv("MCP_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}/mcp"

_PAYLOAD = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "healthcheck", "version": "1.0"},
        },
    }
).encode("utf-8")


def main() -> int:
    request = urllib.request.Request(
        URL,
        data=_PAYLOAD,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            # A 2xx from initialize means the server is alive and handshaking.
            if 200 <= response.status < 300:
                return 0
            print(f"Unhealthy: HTTP {response.status}", file=sys.stderr)
            return 1
    except urllib.error.HTTPError as exc:
        # The endpoint answered (server is up) but rejected the probe.
        print(f"Unhealthy: HTTP {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        print(f"Unhealthy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
