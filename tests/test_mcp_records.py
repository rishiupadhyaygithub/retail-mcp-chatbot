"""Integration tests for Phase 2B MCP Record Query Tools and Schema Resource."""

import asyncio
import json
from server.main import create_server


def test_mcp_discovers_all_tools_and_resources():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]
    expected_tools = {
        "kb_retail_search",
        "kb_retail_query_orders",
        "kb_retail_query_shipments",
        "kb_retail_query_returns",
        "kb_retail_query_customer",
    }
    assert expected_tools.issubset(set(tool_names)), f"Missing tools in {tool_names}"

    resources = asyncio.run(server.list_resources())
    resource_names = [r.name for r in resources]
    expected_resources = {"kb_retail_documents", "kb_retail_schema"}
    assert expected_resources.issubset(set(resource_names)), f"Missing resources in {resource_names}"


def test_mcp_call_query_orders_and_empty_q28():
    server = create_server()
    # 1. Matching order
    raw_res = asyncio.run(server.call_tool("kb_retail_query_orders", {"order_id": "ORD-9031"}))
    data = json.loads(raw_res.content[0].text)
    assert data["total_found"] == 1
    assert data["results"][0]["order_id"] == "ORD-9031"
    assert data["results"][0]["brand"] == "amazon"
    assert len(data["results"][0]["line_items"]) == 1

    # 2. Non-existent order (Q28)
    raw_empty = asyncio.run(server.call_tool("kb_retail_query_orders", {"order_id": "ORD-99999999"}))
    data_empty = json.loads(raw_empty.content[0].text)
    assert data_empty["total_found"] == 0
    assert data_empty["results"] == []


def test_mcp_call_query_shipments_split():
    server = create_server()
    raw_res = asyncio.run(server.call_tool("kb_retail_query_shipments", {"order_id": "ORD-9021"}))
    data = json.loads(raw_res.content[0].text)
    assert data["total_found"] == 2
    statuses = {s["status"] for s in data["results"]}
    assert statuses == {"delivered", "in_transit"}


def test_mcp_call_query_returns_and_customer():
    server = create_server()
    # Returns tool
    raw_ret = asyncio.run(server.call_tool("kb_retail_query_returns", {"customer_id": "CUST-103", "status": "refund_processing"}))
    ret_data = json.loads(raw_ret.content[0].text)
    assert ret_data["total_found"] == 1
    assert ret_data["results"][0]["return_id"] == "RET-701"

    # Customer tool
    raw_cust = asyncio.run(server.call_tool("kb_retail_query_customer", {"customer_id": "CUST-103"}))
    cust_data = json.loads(raw_cust.content[0].text)
    assert cust_data["total_found"] == 1
    aggs = cust_data["results"][0]["aggregates_2026"]
    assert aggs["orders_placed_count"] == 3
    assert aggs["total_refunded_completed"] == 60.48
    assert aggs["open_returns_count"] == 1


def test_mcp_schema_resource():
    server = create_server()
    resource_contents = asyncio.run(server.read_resource("kb://retail/schema"))
    raw_schema = resource_contents[0].content
    schema = json.loads(raw_schema)
    assert schema["resource"] == "kb://retail/schema"
    assert "orders" in schema["tables"]
    assert "shipments" in schema["tables"]
    assert "returns" in schema["tables"]
    assert "supported_tools" in schema
