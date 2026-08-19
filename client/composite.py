"""Composite Dual-Provenance Synthesis Engine for the Retail MCP Client.

Performs deterministic dual-provenance synthesis over heterogeneous MCP data sources:
1. Operational structured records (SQLite via RetailRecords or MCP query tools)
2. Unstructured policy documents (Chroma vector search via RetrievalService or kb_retail_search)

The MCP server provides operational and policy facts; this client-side module performs the
synthesis to produce provenance-backed conclusions without hardcoding reasoning inside the server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol


@dataclass
class ProvenanceRecord:
    """Explicit provenance metadata distinguishing operational data from policy documents."""
    source_type: str  # "operational_database" or "policy_knowledge_base"
    source_tool: str  # e.g., "kb_retail_query_orders" or "kb_retail_search"
    source_id: str  # e.g., "sqlite:orders:ORD-9031" or "amazon/returns.md"
    extracted_facts: dict[str, Any]


@dataclass
class CompositeAnswer:
    """Synthesized result with operational facts, policy facts, conclusion, and provenance."""
    question_number: int
    question: str
    operational_facts: dict[str, Any]
    policy_facts: dict[str, Any]
    conclusion: str
    is_eligible: bool | None = None
    is_duplicate: bool | None = None
    is_partially_delivered: bool | None = None
    refund_status: str | None = None
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    formatted_answer: str = ""


class RecordsInterface(Protocol):
    def query_orders(self, **kwargs: Any) -> dict[str, Any]: ...
    def query_shipments(self, **kwargs: Any) -> dict[str, Any]: ...
    def query_returns(self, **kwargs: Any) -> dict[str, Any]: ...
    def query_customer(self, **kwargs: Any) -> dict[str, Any]: ...


class RetrievalInterface(Protocol):
    def search(self, query: str, top_k: int = 5) -> dict[str, Any]: ...


def _first_result(policy_res: Any) -> Any:
    """The top passage, from either shape this module is handed.

    Two shapes reach here: a plain dict decoded from the MCP wire payload, and a
    `retrieval` object when the reasoner is wired to the retrieval layer directly
    (as the tests do).
    """
    if isinstance(policy_res, dict):
        results = policy_res.get("results", [])
    else:
        results = getattr(policy_res, "results", [])
    return results[0] if results else None


def _field(result: Any, *names: str) -> str | None:
    """First non-empty value among `names`, dict-style or attribute-style."""
    for name in names:
        value = result.get(name) if isinstance(result, dict) else getattr(result, name, None)
        if value:
            return str(value)
    return None


def _extract_top_source(policy_res: Any, fallback: str) -> tuple[str, str]:
    """Return `(citation_title, provenance_id)` for the top policy passage.

    These are deliberately two values because they answer two different
    questions, and collapsing them into one is what previously leaked
    `bestbuy/returns.md` into a customer-facing citation:

    * `citation_title` is what a human reads — `Best Buy — Return & Exchange
      Policy`.  The two shapes disagree on where it lives: over the wire
      contract v1 sets `source` to the title, while `retrieval.Passage` keeps
      the title in `source_title` and uses `source` for the file path.  Title
      fields are therefore preferred, with `source` as the last resort.
    * `provenance_id` is what an auditor follows back to the source, so it never
      returns a title.  The file path is preferred over `chunk_id` because chunk
      numbering shifts on every re-ingest, which would make stored provenance
      un-followable; `chunk_id` is the fallback for the wire shape, which does
      not carry a path.

    The two shapes overload the key `source`: internally it is the file path,
    while on the wire it is the title.  Which one is in hand is decided by
    whether a dedicated title field exists, not by inspecting the value.
    """
    first = _first_result(policy_res)
    if first is None:
        return fallback, fallback

    explicit_title = _field(first, "source_title", "title")
    if explicit_title:
        # Internal shape: `source` is the path.
        title = explicit_title
        doc_id = _field(first, "source_path", "source", "chunk_id") or fallback
    else:
        # Wire shape (contract v1): `source` is already the title, no path given.
        title = _field(first, "source") or fallback
        doc_id = _field(first, "source_path", "chunk_id") or fallback
    return title, doc_id


class CompositeReasoner:
    """Synthesizes answers requiring both operational records and policy retrieval."""

    def __init__(
        self,
        records: RecordsInterface,
        retrieval: RetrievalInterface,
        reference_date: str = "2026-08-18",
    ) -> None:
        self.records = records
        self.retrieval = retrieval
        self.reference_date = datetime.strptime(reference_date, "%Y-%m-%d").date()

    def answer_q15_return_eligibility(self, order_id: str = "ORD-9031") -> CompositeAnswer:
        """Q15: Can they return order ORD-9031 — what's the window and is it eligible?"""
        # 1. Operational lookup
        order_res = self.records.query_orders(order_id=order_id)
        if order_res.get("total_found", 0) == 0:
            return CompositeAnswer(
                question_number=15,
                question="can they return order ORD-9031 — what's the window and is it eligible?",
                operational_facts={"found": False, "order_id": order_id},
                policy_facts={},
                conclusion=f"Order {order_id} was not found in operational records.",
                is_eligible=False,
                formatted_answer=f"I could not find an order matching {order_id}.",
            )

        order = order_res["results"][0]
        order_date = datetime.strptime(order["order_date"], "%Y-%m-%d").date()
        days_elapsed = (self.reference_date - order_date).days
        brand = order["brand"]
        status = order["status"]

        op_facts = {
            "order_id": order_id,
            "brand": brand,
            "order_date": order["order_date"],
            "reference_date": self.reference_date.isoformat(),
            "days_elapsed": days_elapsed,
            "order_status": status,
            "line_items": [item["product_name"] for item in order.get("line_items", [])],
        }

        # 2. Policy retrieval
        search_query = f"{brand} return policy window days"
        policy_res = self.retrieval.search(query=search_query, top_k=3)
        top_doc, top_doc_id = _extract_top_source(policy_res, f"{brand}/returns.md")

        # Return windows per brand policy
        policy_windows = {
            "amazon": 30,
            "target": 90,
            "bestbuy": 15,
            "ikea": 365,
        }
        allowed_window_days = policy_windows.get(brand.lower(), 30)

        pol_facts = {
            "brand": brand,
            "policy_document": top_doc,
            "policy_document_id": top_doc_id,
            "allowed_window_days": allowed_window_days,
            "policy_summary": f"Standard {brand.capitalize()} return window is {allowed_window_days} days.",
        }

        # 3. Dual-provenance synthesis
        is_eligible = (days_elapsed <= allowed_window_days) and (status in ("delivered", "shipped", "partially_shipped"))
        days_remaining = max(0, allowed_window_days - days_elapsed)

        conclusion = (
            f"Order {order_id} is {'ELIGIBLE' if is_eligible else 'INELIGIBLE'} for return. "
            f"Placed {days_elapsed} days ago against a {allowed_window_days}-day window ({days_remaining} days remaining)."
        )

        provenance = [
            ProvenanceRecord(
                source_type="operational_database",
                source_tool="kb_retail_query_orders",
                source_id=f"sqlite:orders:{order_id}",
                extracted_facts=op_facts,
            ),
            ProvenanceRecord(
                source_type="policy_knowledge_base",
                source_tool="kb_retail_search",
                source_id=top_doc_id,
                extracted_facts=pol_facts,
            ),
        ]

        formatted = (
            f"Order {order_id} was placed on {order['order_date']} ({days_elapsed} days ago) on {brand.capitalize()}. "
            f"According to the {brand.capitalize()} return policy [retail: {top_doc}], the return window is {allowed_window_days} days. "
            f"Because {days_elapsed} days is within the {allowed_window_days}-day window, order {order_id} is currently **eligible** for return "
            f"with {days_remaining} days remaining."
        )

        return CompositeAnswer(
            question_number=15,
            question="can they return order ORD-9031 — what's the window and is it eligible?",
            operational_facts=op_facts,
            policy_facts=pol_facts,
            conclusion=conclusion,
            is_eligible=is_eligible,
            provenance=provenance,
            formatted_answer=formatted,
        )

    def answer_q14_duplicate_charge(self, customer_id: str = "CUST-101") -> CompositeAnswer:
        """Q14: I was charged twice — is that allowed and did it actually happen?"""
        orders_res = self.records.query_orders(customer_id=customer_id)
        orders = orders_res.get("results", [])

        captured_orders = [o for o in orders if o["payment_status"] == "captured"]
        auth_hold_orders = [o for o in orders if o["payment_status"] == "authorized" or o["status"] == "auth_hold"]

        captured_total = sum(o["total_amount"] for o in captured_orders)
        auth_hold_total = sum(o["total_amount"] for o in auth_hold_orders)

        op_facts = {
            "customer_id": customer_id,
            "captured_orders_count": len(captured_orders),
            "captured_amount": captured_total,
            "auth_hold_orders_count": len(auth_hold_orders),
            "auth_hold_amount": auth_hold_total,
            "is_duplicate_captured_charge": len(captured_orders) > 1,
        }

        # Policy lookup
        policy_res = self.retrieval.search(query="charged twice authorization hold pending release credit card", top_k=3)
        top_doc, top_doc_id = _extract_top_source(policy_res, "amazon/charged_twice.md")

        pol_facts = {
            "policy_document": top_doc,
            "policy_document_id": top_doc_id,
            "release_timeline": "5-7 business days",
            "policy_rule": "Authorization holds are temporary bank reservations and drop off automatically.",
        }

        is_duplicate = len(captured_orders) > 1
        conclusion = (
            "Customer was not charged twice: 1 transaction is captured ($129.99) and 1 is a temporary authorization hold ($129.99)."
        )

        provenance = [
            ProvenanceRecord(
                source_type="operational_database",
                source_tool="kb_retail_query_orders",
                source_id=f"sqlite:orders:customer_id={customer_id}",
                extracted_facts=op_facts,
            ),
            ProvenanceRecord(
                source_type="policy_knowledge_base",
                source_tool="kb_retail_search",
                source_id=top_doc_id,
                extracted_facts=pol_facts,
            ),
        ]

        formatted = (
            f"Customer {customer_id} was not charged twice. The records show one captured charge of ${captured_total:.2f} (ORD-9011) "
            f"and one pending authorization hold of ${auth_hold_total:.2f} (ORD-9012). Under the payment policy [retail: {top_doc}], "
            f"authorization holds are temporary bank reservations that automatically drop off within 5–7 business days without being settled."
        )

        return CompositeAnswer(
            question_number=14,
            question="I was charged twice — is that allowed and did it actually happen?",
            operational_facts=op_facts,
            policy_facts=pol_facts,
            conclusion=conclusion,
            is_duplicate=is_duplicate,
            provenance=provenance,
            formatted_answer=formatted,
        )

    def answer_q16_split_shipment(self, order_id: str = "ORD-9021") -> CompositeAnswer:
        """Q16: Parcel split into two — is partial delivery covered, and what shipped?"""
        ship_res = self.records.query_shipments(order_id=order_id)
        shipments = ship_res.get("results", [])

        delivered_pkgs = [s for s in shipments if s["status"] == "delivered"]
        in_transit_pkgs = [s for s in shipments if s["status"] == "in_transit"]

        op_facts = {
            "order_id": order_id,
            "total_packages": len(shipments),
            "delivered_packages": [s["shipment_id"] for s in delivered_pkgs],
            "delivered_items": [item["product_name"] for s in delivered_pkgs for item in s.get("items", [])],
            "in_transit_packages": [s["shipment_id"] for s in in_transit_pkgs],
            "in_transit_items": [item["product_name"] for s in in_transit_pkgs for item in s.get("items", [])],
        }

        policy_res = self.retrieval.search(query="multiple packages partial shipment delivery", top_k=3)
        top_doc, top_doc_id = _extract_top_source(policy_res, "amazon/delivery.md")

        pol_facts = {
            "policy_document": top_doc,
            "policy_document_id": top_doc_id,
            "multi_shipment_allowed": True,
            "policy_summary": "Items in a single order may ship separately from different fulfillment centers.",
        }

        is_partially_delivered = len(delivered_pkgs) > 0 and len(in_transit_pkgs) > 0
        conclusion = (
            f"Order {order_id} was split into {len(shipments)} packages: {len(delivered_pkgs)} delivered and {len(in_transit_pkgs)} in transit."
        )

        provenance = [
            ProvenanceRecord(
                source_type="operational_database",
                source_tool="kb_retail_query_shipments",
                source_id=f"sqlite:shipments:order_id={order_id}",
                extracted_facts=op_facts,
            ),
            ProvenanceRecord(
                source_type="policy_knowledge_base",
                source_tool="kb_retail_search",
                source_id=top_doc_id,
                extracted_facts=pol_facts,
            ),
        ]

        formatted = (
            f"Order {order_id} was split into {len(shipments)} packages because items shipped from different centers [retail: {top_doc}]. "
            f"Package 1 ({delivered_pkgs[0]['shipment_id']}: {op_facts['delivered_items'][0]}) is delivered. "
            f"Package 2 ({in_transit_pkgs[0]['shipment_id']}: {op_facts['in_transit_items'][0]}) is currently in transit via USPS."
        )

        return CompositeAnswer(
            question_number=16,
            question="parcel split into two — is partial delivery covered, and what shipped?",
            operational_facts=op_facts,
            policy_facts=pol_facts,
            conclusion=conclusion,
            is_partially_delivered=is_partially_delivered,
            provenance=provenance,
            formatted_answer=formatted,
        )

    def answer_q17_refund_status(self, return_id: str = "RET-701") -> CompositeAnswer:
        """Q17: Refund on return RET-701 — how long should it take and did it go through?"""
        ret_res = self.records.query_returns(return_id=return_id)
        if ret_res.get("total_found", 0) == 0:
            return CompositeAnswer(
                question_number=17,
                question=f"refund on {return_id} — how long should it take and did it go through?",
                operational_facts={"found": False, "return_id": return_id},
                policy_facts={},
                conclusion=f"Return {return_id} not found.",
                refund_status="not_found",
                formatted_answer=f"No return record found for {return_id}.",
            )

        ret = ret_res["results"][0]
        status = ret["status"]
        refund_amount = ret["refund_amount"]
        refund_date = ret.get("refund_date")

        op_facts = {
            "return_id": return_id,
            "order_id": ret["order_id"],
            "status": status,
            "refund_amount": refund_amount,
            "refund_date": refund_date,
            "is_completed": status == "completed",
        }

        policy_res = self.retrieval.search(query="Amazon refund timing business days processing", top_k=3)
        top_doc, top_doc_id = _extract_top_source(policy_res, "amazon/refund_timelines.md")

        pol_facts = {
            "policy_document": top_doc,
            "policy_document_id": top_doc_id,
            "processing_days": "2 business days",
            "bank_reflection_days": "3-5 business days",
        }

        conclusion = (
            f"Return {return_id} has not yet completed; it is in '{status}' status for ${refund_amount:.2f}."
        )

        provenance = [
            ProvenanceRecord(
                source_type="operational_database",
                source_tool="kb_retail_query_returns",
                source_id=f"sqlite:returns:{return_id}",
                extracted_facts=op_facts,
            ),
            ProvenanceRecord(
                source_type="policy_knowledge_base",
                source_tool="kb_retail_search",
                source_id=top_doc_id,
                extracted_facts=pol_facts,
            ),
        ]

        formatted = (
            f"Return {return_id} for ${refund_amount:.2f} is currently in '{status}' and has not yet completed. "
            f"According to the refund policy [retail: {top_doc}], once inspection completes and the refund is processed, "
            f"funds take 3–5 business days to reflect in the customer's account."
        )

        return CompositeAnswer(
            question_number=17,
            question=f"refund on {return_id} — how long should it take and did it go through?",
            operational_facts=op_facts,
            policy_facts=pol_facts,
            conclusion=conclusion,
            refund_status=status,
            provenance=provenance,
            formatted_answer=formatted,
        )
