"""The frozen application payloads for the retail MCP search tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from retrieval import SearchResponse


@dataclass(frozen=True)
class SearchRequest:
    query: str
    top_k: int
    document_type: str | None


def invalid_parameter(message: str) -> dict[str, Any]:
    return {"error": "invalid_parameter", "message": message, "retryable": False}


def internal_error(message: str = "Search service temporarily unavailable") -> dict[str, Any]:
    return {"error": "internal_error", "message": message, "retryable": True}


def validate_search_request(
    query: Any, top_k: Any = 5, filters: Any = None, unknown: dict[str, Any] | None = None
) -> SearchRequest | dict[str, Any]:
    """Validate only the contract-defined tool arguments and nothing broader."""
    if unknown:
        return invalid_parameter(f"unknown parameter: {sorted(unknown)[0]}")
    if type(query) is not str or not query.strip():
        return invalid_parameter("query must be a non-empty string")
    if type(top_k) is not int or top_k <= 0:
        return invalid_parameter("top_k must be a positive integer")
    if filters is None:
        return SearchRequest(query=query, top_k=top_k, document_type=None)
    if type(filters) is not dict:
        return invalid_parameter("filters must be an object")
    unknown = set(filters) - {"document_type"}
    if unknown:
        return invalid_parameter("filters only supports document_type")
    document_type = filters.get("document_type")
    if document_type is not None and (type(document_type) is not str or not document_type.strip()):
        return invalid_parameter("filters.document_type must be a non-empty string")
    return SearchRequest(query=query, top_k=top_k, document_type=document_type)


def format_search_response(response: SearchResponse) -> dict[str, Any]:
    """Map frozen retrieval records to contract v1 field names and semantics."""
    return {
        "results": [
            {
                "content": result.content,
                # Contract v1 calls this a document title.  The source path remains
                # available as the deterministic ID in kb_retail_documents.
                "source": result.source_title,
                "section": result.section,
                "score": result.score,
                "chunk_id": result.chunk_id,
            }
            for result in response.results
        ],
        "query": response.query,
        "total_found": response.total_found,
    }
