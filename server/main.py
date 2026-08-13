#!/usr/bin/env python3
"""Retail MCP server: a thin protocol adapter over frozen Phase A retrieval."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

# Keep the documented `python3 server/main.py` invocation working as well as
# `python3 -m server.main`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import ConfigDict

from server.retrieval import RetrievalFailure, RetrievalUnavailable, RetailRetrieval, SearchResponse
from server.schemas import (
    SearchRequest,
    format_search_response,
    internal_error,
    validate_search_request,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8003

# Contract v1 §7 transport names -> the SDK's transport names.
TRANSPORTS = {"stdio": "stdio", "http": "streamable-http", "sse": "sse"}

_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer", "default": 5},
        "filters": {
            "type": "object",
            "properties": {"document_type": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class _RawSearchArguments(ArgModelBase):
    """Pass raw tool arguments to the contract validator without losing extras.

    The SDK otherwise rejects missing/wrongly typed values before a tool can
    return contract_v1's required application payload, and silently ignores
    unknown keys.  The published JSON schema remains strict; this model exists
    only to route malformed *tool arguments* to the agreed error shape.
    """

    query: Any = None
    top_k: Any = 5
    filters: Any = None
    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:
        values = super().model_dump_one_level()
        values["unknown"] = dict(self.model_extra or {})
        return values


class RetrievalPort(Protocol):
    def initialize(self) -> None: ...

    def search(
        self, query: str, *, top_k: int, document_type: str | None
    ) -> SearchResponse: ...

    def documents(self) -> list[dict[str, str]]: ...


def _as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def create_server(retrieval: RetrievalPort | None = None) -> MCPServer:
    """Create the MCP surface; injected retrieval keeps protocol tests independent of local data.

    Host and port are not constructor arguments: since mcp 2.0.0 they belong to
    the chosen transport and are passed by `run_server`.
    """
    active_retrieval = retrieval or RetailRetrieval()

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        # Startup is intentionally eager: normal calls never reload the BGE model
        # or reconnect Chroma.  A failed local dependency remains an MCP server
        # that can return a controlled tool error rather than a stack trace.
        initialize = getattr(active_retrieval, "initialize", None)
        if callable(initialize):
            try:
                initialize()
            except RetrievalUnavailable:
                LOGGER.exception("Retail retrieval was unavailable during server startup")
        yield

    mcp = MCPServer(
        "Retail Knowledge Base",
        instructions=(
            "Use kb_retail_search for retail policy and help documentation. "
            "Returned passages are retrieval evidence; do not invent facts beyond them."
        ),
        lifespan=lifespan,
    )

    @mcp.tool(
        name="kb_retail_search",
        description=(
            "Search retail policy and help documentation for returns, delivery, payments, "
            "and warranties. Use when a question is about a retail rule, policy, or procedure. "
            "Do not use for a specific customer's actual order, shipment, or return status."
        ),
    )
    def kb_retail_search(
        query: Any = None,
        top_k: Any = 5,
        filters: Any = None,
        unknown: dict[str, Any] | None = None,
    ) -> str:
        """Return the frozen contract-v1 JSON payload, including successful empty results."""
        request = validate_search_request(query, top_k, filters, unknown)
        if not isinstance(request, SearchRequest):
            return _as_json(request)
        try:
            response = active_retrieval.search(
                request.query, top_k=request.top_k, document_type=request.document_type
            )
            return _as_json(format_search_response(response))
        except (RetrievalUnavailable, RetrievalFailure):
            LOGGER.exception("Retail search failed")
            return _as_json(internal_error())
        except Exception:  # The client must never receive a local traceback.
            LOGGER.exception("Unexpected retail search failure")
            return _as_json(internal_error())

    # Keep tools/list aligned with the shared schema while deliberately sending
    # malformed tool *arguments* to our validator. This narrow customization is
    # necessary because the frozen contract requires an application payload for
    # malformed input, whereas the SDK's default behavior is a ToolError.
    registered_tool = mcp._tool_manager.get_tool("kb_retail_search")
    assert registered_tool is not None
    original_metadata = registered_tool.fn_metadata
    registered_tool.parameters = _SEARCH_INPUT_SCHEMA
    registered_tool.fn_metadata = FuncMetadata(
        arg_model=_RawSearchArguments,
        output_schema=original_metadata.output_schema,
        output_model=original_metadata.output_model,
        wrap_output=original_metadata.wrap_output,
    )

    @mcp.resource(
        "kb://retail/documents",
        name="kb_retail_documents",
        title="Retail knowledge-base documents",
        description="Read-only list of the retail knowledge-base document titles and IDs.",
        mime_type="application/json",
    )
    def kb_retail_documents() -> str:
        try:
            return _as_json({"documents": active_retrieval.documents()})
        except (RetrievalUnavailable, RetrievalFailure):
            LOGGER.exception("Retail document resource failed")
            return _as_json(internal_error("Document list temporarily unavailable"))
        except Exception:
            LOGGER.exception("Unexpected retail document resource failure")
            return _as_json(internal_error("Document list temporarily unavailable"))

    @mcp.prompt(
        name="kb_retail_search_template",
        title="Retail knowledge-base search guidance",
        description="Guidance for using the retail policy-document search tool.",
    )
    def kb_retail_search_template() -> str:
        return (
            "Use kb_retail_search for a retail policy or help-document question. "
            "Answer only from returned passages, and cite the returned source title. "
            "Use a record-query tool instead for a specific customer's order or shipment."
        )

    return mcp


def run_server(
    mcp: MCPServer,
    transport: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Start `mcp` on a contract v1 §7 transport name.

    stdio takes no address; the network transports take host and port here
    rather than at construction, which is where mcp 2.0.0 moved them.  The SDK
    default host is 127.0.0.1, so binding every interface for interop day is an
    explicit argument, never an inherited default.
    """
    sdk_transport = TRANSPORTS[transport]
    if sdk_transport == "stdio":
        mcp.run("stdio")
        return
    mcp.run(sdk_transport, host=host, port=port)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Retail MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "sse"),
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help=(
            "stdio for local clients; http is contract v1's network transport and runs "
            "MCP Streamable HTTP at /mcp; sse is the deprecated pre-2025-03-26 transport, "
            "kept only for a client that cannot speak Streamable HTTP yet."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Contract v1 §7 names the network transport "http".  MCP deprecated the SSE
    # transport in spec revision 2025-03-26; this project targets 2026-07-28, so
    # "http" maps to Streamable HTTP (endpoint /mcp).  --transport sse remains
    # selectable for a client that has not migrated yet.
    run_server(create_server(), args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
