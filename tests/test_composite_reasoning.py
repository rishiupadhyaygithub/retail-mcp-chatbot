"""Unit and integration tests for Phase 2E Composite Reasoning (Dual Provenance).

Demonstrates:
  user question -> multiple MCP tools -> heterogeneous data sources (SQLite + Chroma)
  -> provenance-aware synthesis -> correct answer.

Primary showcase: Q15 (Return Window & Eligibility).
Secondary showcases: Q14 (Duplicate charge vs auth hold), Q16 (Split shipment), Q17 (Refund timing).
"""

import asyncio
import json
from server.records import RetailRecords
from server.retrieval import RetailRetrieval
from client.composite import CompositeReasoner, ProvenanceRecord


def test_q15_primary_showcase_return_eligibility_and_dual_provenance():
    records = RetailRecords()
    retrieval = RetailRetrieval()
    reasoner = CompositeReasoner(records, retrieval, reference_date="2026-08-18")

    # 1. Eligible order: ORD-9031 (placed 2026-08-06, 12 days elapsed, Amazon 30-day window)
    ans = reasoner.answer_q15_return_eligibility("ORD-9031")
    assert ans.question_number == 15
    assert ans.is_eligible is True
    assert ans.operational_facts["order_id"] == "ORD-9031"
    assert ans.operational_facts["brand"] == "amazon"
    assert ans.operational_facts["days_elapsed"] == 12
    assert ans.policy_facts["allowed_window_days"] == 30
    assert "amazon/returns.md" in ans.policy_facts["policy_document"]

    # Verify Dual Provenance
    assert len(ans.provenance) == 2
    sources = {p.source_type: p for p in ans.provenance}
    assert "operational_database" in sources
    assert "policy_knowledge_base" in sources

    op_prov = sources["operational_database"]
    assert op_prov.source_tool == "kb_retail_query_orders"
    assert op_prov.source_id == "sqlite:orders:ORD-9031"
    assert op_prov.extracted_facts["order_date"] == "2026-08-06"

    pol_prov = sources["policy_knowledge_base"]
    assert pol_prov.source_tool == "kb_retail_search"
    assert "amazon/returns.md" in pol_prov.source_id
    assert pol_prov.extracted_facts["allowed_window_days"] == 30

    # Verify formatted agent response
    assert "[retail: amazon/returns.md]" in ans.formatted_answer
    assert "eligible" in ans.formatted_answer.lower()
    assert "18 days remaining" in ans.formatted_answer


def test_q15_ineligible_order_scenario():
    records = RetailRecords()
    retrieval = RetailRetrieval()
    reasoner = CompositeReasoner(records, retrieval, reference_date="2026-08-18")

    # Ineligible order: ORD-9032 (Best Buy order placed 2026-07-01, 48 days elapsed vs 15-day window)
    ans = reasoner.answer_q15_return_eligibility("ORD-9032")
    assert ans.is_eligible is False
    assert ans.operational_facts["brand"] == "bestbuy"
    assert ans.operational_facts["days_elapsed"] == 48
    assert ans.policy_facts["allowed_window_days"] == 15
    assert "INELIGIBLE" in ans.conclusion


def test_q14_duplicate_charge_vs_auth_hold():
    records = RetailRecords()
    retrieval = RetailRetrieval()
    reasoner = CompositeReasoner(records, retrieval, reference_date="2026-08-18")

    ans = reasoner.answer_q14_duplicate_charge("CUST-101")
    assert ans.question_number == 14
    assert ans.is_duplicate is False
    assert ans.operational_facts["captured_orders_count"] == 1
    assert ans.operational_facts["captured_amount"] == 129.99
    assert ans.operational_facts["auth_hold_orders_count"] == 1
    assert ans.operational_facts["auth_hold_amount"] == 129.99
    assert "amazon/charged_twice.md" in ans.policy_facts["policy_document"]

    # Verify Dual Provenance
    assert len(ans.provenance) == 2
    assert ans.provenance[0].source_tool == "kb_retail_query_orders"
    assert ans.provenance[1].source_tool == "kb_retail_search"
    assert "not charged twice" in ans.formatted_answer.lower()
    assert "5–7 business days" in ans.formatted_answer


def test_q16_split_shipment_partial_delivery():
    records = RetailRecords()
    retrieval = RetailRetrieval()
    reasoner = CompositeReasoner(records, retrieval, reference_date="2026-08-18")

    ans = reasoner.answer_q16_split_shipment("ORD-9021")
    assert ans.question_number == 16
    assert ans.is_partially_delivered is True
    assert ans.operational_facts["total_packages"] == 2
    assert ans.operational_facts["delivered_packages"] == ["SHIP-402"]
    assert "Ninja Personal Blender" in ans.operational_facts["delivered_items"]
    assert ans.operational_facts["in_transit_packages"] == ["SHIP-403"]
    assert "Brita Water Filter Pitcher (6 Cup)" in ans.operational_facts["in_transit_items"]
    assert "[retail: " in ans.formatted_answer


def test_q17_refund_processing_status_and_timelines():
    records = RetailRecords()
    retrieval = RetailRetrieval()
    reasoner = CompositeReasoner(records, retrieval, reference_date="2026-08-18")

    ans = reasoner.answer_q17_refund_status("RET-701")
    assert ans.question_number == 17
    assert ans.refund_status == "refund_processing"
    assert ans.operational_facts["refund_amount"] == 89.50
    assert ans.operational_facts["is_completed"] is False
    assert "3-5 business days" in ans.policy_facts["bank_reflection_days"]
    assert "refund_processing" in ans.formatted_answer
    assert "[retail: amazon/refund_timelines.md]" in ans.formatted_answer


def test_composite_over_live_mcp_client():
    """Verify composite reasoning executed through the live MCP FastMCP server."""
    from server.main import create_server
    server = create_server()

    # Wrap MCP server tools as Records and Retrieval interfaces
    class MCPRecordsAdapter:
        def query_orders(self, **kwargs):
            res = asyncio.run(server.call_tool("kb_retail_query_orders", kwargs))
            return json.loads(res.content[0].text)

        def query_shipments(self, **kwargs):
            res = asyncio.run(server.call_tool("kb_retail_query_shipments", kwargs))
            return json.loads(res.content[0].text)

        def query_returns(self, **kwargs):
            res = asyncio.run(server.call_tool("kb_retail_query_returns", kwargs))
            return json.loads(res.content[0].text)

        def query_customer(self, **kwargs):
            res = asyncio.run(server.call_tool("kb_retail_query_customer", kwargs))
            return json.loads(res.content[0].text)

    class MCPRetrievalAdapter:
        def search(self, query: str, top_k: int = 5):
            res = asyncio.run(server.call_tool("kb_retail_search", {"query": query, "top_k": top_k}))
            return json.loads(res.content[0].text)

    mcp_reasoner = CompositeReasoner(
        records=MCPRecordsAdapter(),
        retrieval=MCPRetrievalAdapter(),
        reference_date="2026-08-18",
    )

    # Test Q15 primary showcase through MCP tool calls
    ans = mcp_reasoner.answer_q15_return_eligibility("ORD-9031")
    assert ans.is_eligible is True
    assert ans.operational_facts["brand"] == "amazon"
    assert ans.operational_facts["days_elapsed"] == 12
    assert "eligible" in ans.formatted_answer.lower()
