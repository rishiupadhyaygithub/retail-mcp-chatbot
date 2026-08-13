"""Live network-transport test.

Contract v1 §7 requires a network transport for interop day. MCP deprecated the
SSE transport in spec revision 2025-03-26 and this project targets 2026-07-28,
so `--transport http` must serve Streamable HTTP at `/mcp`. Nothing in the
in-process tests would catch a regression back to SSE, which is why this test
starts a real server and speaks to it over a real socket.
"""

import asyncio
import json
import socket
import threading
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from server.main import TRANSPORTS, create_server
from tests.test_mcp_server import FakeRetrieval


HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((HOST, port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"server did not start listening on {HOST}:{port}")


def test_contract_http_maps_to_streamable_http_not_sse() -> None:
    """The deprecated transport must not be what `http` selects."""
    assert TRANSPORTS["http"] == "streamable-http"
    assert TRANSPORTS["stdio"] == "stdio"
    # Kept selectable for a client that has not migrated, but never the default.
    assert TRANSPORTS["sse"] == "sse"


def test_streamable_http_serves_discovery_and_tool_calls_over_a_socket() -> None:
    port = _free_port()
    server = create_server(FakeRetrieval(), host=HOST, port=port)
    threading.Thread(
        target=lambda: server.run(TRANSPORTS["http"]), daemon=True
    ).start()
    _wait_until_listening(port)

    async def exercise() -> tuple[list[str], dict]:
        async with streamable_http_client(f"http://{HOST}:{port}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool(
                    "kb_retail_search", {"query": "when is my refund due?", "top_k": 1}
                )
                return [tool.name for tool in tools.tools], json.loads(result.content[0].text)

    tool_names, payload = asyncio.run(exercise())

    assert tool_names == ["kb_retail_search"]
    assert payload["total_found"] == 1
    assert payload["results"][0]["chunk_id"] == "retail-doc-3:chunk-1"
