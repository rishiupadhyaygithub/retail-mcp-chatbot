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

from server.records import RetailRecords, get_retail_schema
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

    model_config = ConfigDict(extra="allow")
    query: Any = None
    top_k: Any = 5
    filters: Any = None

    def model_dump_one_level(self) -> dict[str, Any]:
        values = super().model_dump_one_level()
        values["unknown"] = dict(self.model_extra or {})
        return values


class RetrievalPort(Protocol):
    def search(
        self, query: str, *, top_k: int, document_type: str | None
    ) -> SearchResponse: ...

    def documents(self) -> list[dict[str, str]]: ...


def _as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def create_server(
    retrieval: RetrievalPort | None = None,
    records: RetailRecords | None = None,
) -> MCPServer:
    """Create the MCP surface; injected retrieval and records keep protocol tests independent of local data.

    Host and port are not constructor arguments: since mcp 2.0.0 they belong to
    the chosen transport and are passed by `run_server`.
    """
    active_retrieval = retrieval or RetailRetrieval()
    active_records = records or RetailRecords()

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
            "Use kb_retail_query_orders, kb_retail_query_shipments, kb_retail_query_returns, "
            "and kb_retail_query_customer for specific operational records and status lookups. "
            "Returned passages and records are retrieval evidence; do not invent facts beyond them."
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

    @mcp.tool(
        name="kb_retail_query_orders",
        description=(
            "Lookup retail customer order details, dates, fulfillment statuses, totals, and line items. "
            "Use when a question is about a specific order or customer order history. "
            "Do not use for policy rules."
        ),
    )
    def kb_retail_query_orders(
        order_id: str | None = None,
        customer_id: str | None = None,
        brand: str | None = None,
        limit: int = 10,
    ) -> str:
        """Return structured order records matching the lookup parameters."""
        try:
            res = active_records.query_orders(
                order_id=order_id, customer_id=customer_id, brand=brand, limit=limit
            )
            return _as_json(res)
        except Exception:
            LOGGER.exception("Unexpected order query failure")
            return _as_json(internal_error("Order query temporarily unavailable"))

    @mcp.tool(
        name="kb_retail_query_shipments",
        description=(
            "Lookup fulfillment tracking numbers, shipping carriers, ship dates, estimated delivery, "
            "and package items. Supports split shipments where items ship in separate packages. "
            "Use for tracking and parcel delivery status."
        ),
    )
    def kb_retail_query_shipments(
        order_id: str | None = None,
        tracking_number: str | None = None,
        shipment_id: str | None = None,
    ) -> str:
        """Return structured shipment and tracking records."""
        try:
            res = active_records.query_shipments(
                order_id=order_id, tracking_number=tracking_number, shipment_id=shipment_id
            )
            return _as_json(res)
        except Exception:
            LOGGER.exception("Unexpected shipment query failure")
            return _as_json(internal_error("Shipment query temporarily unavailable"))

    @mcp.tool(
        name="kb_retail_query_returns",
        description=(
            "Lookup return requests, RMA codes, return reasons, condition, refund amounts, "
            "and return processing states (e.g. requested, in_transit, inspecting, refund_processing, completed). "
            "Use for checking existing return and refund status."
        ),
    )
    def kb_retail_query_returns(
        customer_id: str | None = None,
        order_id: str | None = None,
        return_id: str | None = None,
        rma_code: str | None = None,
        status: str | None = None,
    ) -> str:
        """Return structured return and refund records."""
        try:
            res = active_records.query_returns(
                customer_id=customer_id, order_id=order_id, return_id=return_id, rma_code=rma_code, status=status
            )
            return _as_json(res)
        except Exception:
            LOGGER.exception("Unexpected return query failure")
            return _as_json(internal_error("Return query temporarily unavailable"))

    @mcp.tool(
        name="kb_retail_query_customer",
        description=(
            "Lookup customer account profile and operational summary aggregates "
            "(total orders placed, total refunded, open returns count, pending refund amount). "
            "Use for customer-level history and account totals."
        ),
    )
    def kb_retail_query_customer(
        customer_id: str | None = None,
        email: str | None = None,
    ) -> str:
        """Return customer profile and deterministic operational aggregates."""
        try:
            res = active_records.query_customer(customer_id=customer_id, email=email)
            return _as_json(res)
        except Exception:
            LOGGER.exception("Unexpected customer query failure")
            return _as_json(internal_error("Customer query temporarily unavailable"))

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

    @mcp.resource(
        "kb://retail/schema",
        name="kb_retail_schema",
        title="Retail operational database schema",
        description="Semantic schema describing the retail operational tables (orders, line items, shipments, returns, customers) and their relationships.",
        mime_type="application/json",
    )
    def kb_retail_schema() -> str:
        try:
            return _as_json(get_retail_schema())
        except Exception:
            LOGGER.exception("Unexpected schema resource failure")
            return _as_json(internal_error("Schema resource temporarily unavailable"))

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
