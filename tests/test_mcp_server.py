"""MCP surface tests through FastMCP's public server interface."""

import asyncio
import json

from retrieval import SearchResponse, SearchResult
from server.main import create_server


class FakeRetrieval:
    def search(self, query: str, *, top_k: int, document_type: str | None) -> SearchResponse:
        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    content="# Refund timing\n\nRefunds arrive in 3–5 business days.",
                    source="amazon/refund_timelines.md",
                    source_title="Amazon refund timelines",
                    section="When refunds arrive",
                    score=0.82,
                    chunk_id="retail-doc-3:chunk-1",
                )
            ],
        )

    def documents(self) -> list[dict[str, str]]:
        return [{"id": "amazon/refund_timelines.md", "title": "Amazon refund timelines", "document_type": "payments"}]


class EmptyRetrieval(FakeRetrieval):
    def search(self, query: str, *, top_k: int, document_type: str | None) -> SearchResponse:
        return SearchResponse(query=query, results=[])


def test_tool_call_returns_contract_json() -> None:
    server = create_server(FakeRetrieval())

    content, _structured = asyncio.run(
        server.call_tool("kb_retail_search", {"query": "when is my refund due?", "top_k": 1})
    )

    payload = json.loads(content[0].text)
    assert payload["query"] == "when is my refund due?"
    assert payload["total_found"] == 1
    assert payload["results"][0]["source"] == "Amazon refund timelines"


def test_missing_query_returns_the_application_error_payload() -> None:
    server = create_server(FakeRetrieval())

    content, _structured = asyncio.run(server.call_tool("kb_retail_search", {}))

    assert json.loads(content[0].text) == {
        "error": "invalid_parameter",
        "message": "query must be a non-empty string",
        "retryable": False,
    }


def test_empty_search_is_a_successful_contract_response() -> None:
    server = create_server(EmptyRetrieval())

    content, _structured = asyncio.run(server.call_tool("kb_retail_search", {"query": "no match"}))

    assert json.loads(content[0].text) == {
        "results": [],
        "query": "no match",
        "total_found": 0,
    }


def test_wrong_type_and_unknown_parameter_return_application_errors() -> None:
    server = create_server(FakeRetrieval())

    wrong_type, _ = asyncio.run(server.call_tool("kb_retail_search", {"query": 123}))
    unknown, _ = asyncio.run(
        server.call_tool("kb_retail_search", {"query": "refund", "brand": "amazon"})
    )

    assert json.loads(wrong_type[0].text)["error"] == "invalid_parameter"
    assert json.loads(unknown[0].text) == {
        "error": "invalid_parameter",
        "message": "unknown parameter: brand",
        "retryable": False,
    }


def test_discovery_exposes_the_frozen_tool_schema() -> None:
    server = create_server(FakeRetrieval())

    tools = asyncio.run(server.list_tools())

    tool = next(tool for tool in tools if tool.name == "kb_retail_search")
    assert tool.inputSchema["required"] == ["query"]
    assert tool.inputSchema["properties"]["query"] == {"type": "string"}


def test_resource_and_prompt_are_discoverable_and_useful() -> None:
    server = create_server(FakeRetrieval())

    resources = asyncio.run(server.list_resources())
    documents = asyncio.run(server.read_resource("kb://retail/documents"))
    prompts = asyncio.run(server.list_prompts())
    prompt = asyncio.run(server.get_prompt("kb_retail_search_template", {}))

    assert resources[0].name == "kb_retail_documents"
    assert json.loads(documents[0].content)["documents"][0]["id"] == "amazon/refund_timelines.md"
    assert prompts[0].name == "kb_retail_search_template"
    assert "kb_retail_search" in prompt.messages[0].content.text
