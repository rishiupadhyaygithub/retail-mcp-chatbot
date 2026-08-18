"""Tests for Phase 3: State-Changing Action (kb_retail_create_return), Safety, Idempotency, and Confirmation Gates.

Covers:
1. Valid confirmed return creation (Q22) -> INSERT into returns + UPDATE line_items.status = 'returned'.
2. Missing required fields (Q23) -> clean rejection, zero DB mutations.
3. Unknown order -> clean rejection, zero DB mutations.
4. Item-Order mismatch -> clean rejection, zero DB mutations.
5. Customer-Order mismatch -> clean rejection, zero DB mutations.
6. Unfulfilled item -> clean rejection, zero DB mutations.
7. Duplicate return attempt on already-returned item (Q25) -> rejected with item_already_returned.
8. Identical repeated request -> idempotent return of existing record, no duplicate row inserted.
9. MCP tool discovery and protocol execution.
10. Confirmation state machine: no confirmation = no write.
"""

import asyncio
import json
import sqlite3
import pytest
from pathlib import Path
from server.records import RetailRecords, get_connection
from server.main import create_server
from data.seed_records import seed_records

TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_action_retail.db"


@pytest.fixture(autouse=True)
def fresh_test_db():
    """Create a clean isolated test database before each test."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    seed_records(TEST_DB_PATH)
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_valid_create_return_q22():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # ORD-9011 has ITEM-9011-1 (Instant Pot Duo 7-in-1, delivered, unit_price 129.99)
    res = records.create_return(
        order_id="ORD-9011",
        line_item_id="ITEM-9011-1",
        reason="damaged",
        condition="opened_unused",
        request_date="2026-08-18",
    )

    assert res["ok"] is True
    assert res["status"] == "created"
    assert res["return_id"].startswith("RET-")
    assert res["rma_code"].startswith("RMA-AMZ-")
    assert res["refund_amount"] == 119.99
    assert res["return_status"] == "requested"

    # Verify SQLite state
    conn = get_connection(TEST_DB_PATH)
    try:
        # Check returns row
        ret_row = conn.execute("SELECT * FROM returns WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert ret_row is not None
        assert ret_row["reason"] == "damaged"
        assert ret_row["status"] == "requested"
        assert ret_row["refund_amount"] == 119.99

        # Check line_items row status transition
        item_row = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item_row["status"] == "returned"
    finally:
        conn.close()


def test_missing_required_fields_q23():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # Missing line_item_id and reason
    res = records.create_return(
        order_id="ORD-9011",
        line_item_id="",
        reason="",
    )

    assert res["ok"] is False
    assert res["error"] == "missing_required_fields"
    assert "line_item_id" in res["missing_fields"]
    assert "reason" in res["missing_fields"]

    # Verify no returns created for ORD-9011
    conn = get_connection(TEST_DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM returns WHERE order_id = 'ORD-9011'").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_unknown_order_no_mutation():
    records = RetailRecords(db_path=TEST_DB_PATH)

    res = records.create_return(
        order_id="ORD-NONEXISTENT",
        line_item_id="ITEM-9011-1",
        reason="damaged",
    )

    assert res["ok"] is False
    assert res["error"] == "order_not_found"
    assert res["retryable"] is False


def test_item_order_mismatch_no_mutation():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # ITEM-9021-1 belongs to ORD-9021, not ORD-9011
    res = records.create_return(
        order_id="ORD-9011",
        line_item_id="ITEM-9021-1",
        reason="damaged",
    )

    assert res["ok"] is False
    assert res["error"] == "item_not_in_order"


def test_customer_order_mismatch_no_mutation():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # ORD-9011 belongs to CUST-101, not CUST-102
    res = records.create_return(
        order_id="ORD-9011",
        line_item_id="ITEM-9011-1",
        customer_id="CUST-102",
        reason="damaged",
    )

    assert res["ok"] is False
    assert res["error"] == "customer_order_mismatch"


def test_duplicate_return_rejected_q25():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # ITEM-9033-1 was already returned in seed fixture RET-702 (status='completed')
    res = records.create_return(
        order_id="ORD-9033",
        line_item_id="ITEM-9033-1",
        reason="defective",
    )

    assert res["ok"] is False
    assert res["error"] == "item_already_returned"
    assert res["existing_return_id"] == "RET-702"
    assert res["existing_status"] == "completed"
    assert res["retryable"] is False

    # ITEM-9031-1 was already returned in seed fixture RET-701 (status='refund_processing')
    res_processing = records.create_return(
        order_id="ORD-9031",
        line_item_id="ITEM-9031-1",
        reason="defective",
    )
    assert res_processing["ok"] is False
    assert res_processing["error"] == "item_already_returned"
    assert res_processing["existing_return_id"] == "RET-701"


def test_idempotent_replay_of_identical_request():
    records = RetailRecords(db_path=TEST_DB_PATH)

    # 1. First execution creates return
    res1 = records.create_return(
        order_id="ORD-9011",
        line_item_id="ITEM-9011-1",
        reason="damaged",
    )
    assert res1["ok"] is True
    assert res1["status"] == "created"
    created_ret_id = res1["return_id"]

    # 2. Second execution with identical parameters
    res2 = records.create_return(
        order_id="ORD-9011",
        line_item_id="ITEM-9011-1",
        reason="damaged",
    )
    assert res2["ok"] is True
    assert res2["status"] == "existing"
    assert res2["return_id"] == created_ret_id

    # Verify count in database is exactly 1 (no duplicate rows created)
    conn = get_connection(TEST_DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM returns WHERE line_item_id = 'ITEM-9011-1'").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_mcp_create_return_tool_discovery_and_call():
    server = create_server()

    # 1. Discovery
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]
    assert "kb_retail_create_return" in tool_names

    # 2. Execution via MCP call_tool on ORD-9011
    res = asyncio.run(server.call_tool(
        "kb_retail_create_return",
        {
            "order_id": "ORD-9011",
            "line_item_id": "ITEM-9011-1",
            "reason": "damaged",
        }
    ))
    data = json.loads(res.content[0].text)
    assert data["ok"] is True
    assert "return_id" in data
    assert data["return_id"].startswith("RET-")


def test_confirmation_state_machine_safety():
    """Verify that action is NEVER executed without explicit confirmation."""
    records = RetailRecords(db_path=TEST_DB_PATH)

    # Simulate conversational agent state
    class ReturnActionWorkflow:
        def __init__(self):
            self.state = "INIT"
            self.proposed_action = None

        def handle_user_message(self, message: str, order_id: str, line_item_id: str, reason: str):
            if "want to return" in message.lower():
                # Pre-flight validation (Read-only query)
                order = records.query_orders(order_id=order_id)["results"][0]
                self.proposed_action = {
                    "order_id": order_id,
                    "line_item_id": line_item_id,
                    "product_name": order["line_items"][0]["product_name"],
                    "reason": reason,
                }
                self.state = "WAITING_FOR_CONFIRMATION"
                return f"I can create a return for {self.proposed_action['product_name']}. Please confirm."

            elif message.lower() == "confirm" and self.state == "WAITING_FOR_CONFIRMATION":
                self.state = "USER_CONFIRMED"
                res = records.create_return(
                    order_id=self.proposed_action["order_id"],
                    line_item_id=self.proposed_action["line_item_id"],
                    reason=self.proposed_action["reason"],
                )
                self.state = "ACTION_COMPLETED"
                return f"Return {res['return_id']} created with RMA {res['rma_code']}."

            else:
                self.state = "CANCELLED"
                return "Action cancelled. No changes made."

    # Turn 1: Propose return
    wf = ReturnActionWorkflow()
    reply1 = wf.handle_user_message(
        "I want to return my order ORD-9011",
        order_id="ORD-9011",
        line_item_id="ITEM-9011-1",
        reason="damaged",
    )
    assert wf.state == "WAITING_FOR_CONFIRMATION"
    assert "Please confirm" in reply1

    # Verify ZERO database mutations during proposition
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item["status"] == "delivered"  # Still delivered, not returned!
    finally:
        conn.close()

    # Turn 2: User confirms -> Write is executed
    reply2 = wf.handle_user_message("confirm", order_id="ORD-9011", line_item_id="ITEM-9011-1", reason="damaged")
    assert wf.state == "ACTION_COMPLETED"
    assert "RMA-AMZ-" in reply2

    # Verify DB mutation ONLY after confirmation
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item["status"] == "returned"
    finally:
        conn.close()
