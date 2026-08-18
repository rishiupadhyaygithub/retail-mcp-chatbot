"""Tests for Conversational Workflow Engine (Phase 3C/3D).

Verifies:
1. Q22: Multi-turn return creation with strict confirmation gate (No write before confirmation).
2. Clean cancellation when user rejects confirmation (Zero DB mutations).
3. Q23: Missing required parameters -> prompts for order/item without inventing.
4. Q24: Multi-turn contextual resolution from prior turn.
5. Q25: Loud non-retryable refusal for already-returned item.
6. Q26/Q27/Q28: Honest refusals for out-of-scope/unanswerable questions.
"""

import pytest
from pathlib import Path
from server.records import RetailRecords, get_connection
from server.retrieval import RetailRetrieval
from client.workflow import ConversationalWorkflow, WorkflowState
from data.seed_records import seed_records

TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_workflow_retail.db"


@pytest.fixture(autouse=True)
def fresh_test_db():
    """Create a clean isolated test database before each test."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    seed_records(TEST_DB_PATH)
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_q22_multi_turn_return_creation_with_confirmation_gate():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    # Turn 1: Propose return
    reply1 = wf.handle_turn("open a return for order ORD-9011, item ITEM-9011-1, reason damaged")
    assert wf.state == WorkflowState.WAITING_FOR_CONFIRMATION
    assert "Kindle Paperwhite" in reply1
    assert "$119.99" in reply1
    assert "Please confirm" in reply1

    # CRITICAL INVARIANT: Zero database mutations during proposition turn!
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item["status"] == "delivered"  # Not mutated!
        ret_count = conn.execute("SELECT COUNT(*) FROM returns WHERE line_item_id = 'ITEM-9011-1'").fetchone()[0]
        assert ret_count == 0  # No return created yet!
    finally:
        conn.close()

    # Turn 2: Explicit user confirmation
    reply2 = wf.handle_turn("Yes, please proceed")
    assert wf.state == WorkflowState.ACTION_COMPLETED
    assert "Return successfully created" in reply2
    assert "RET-" in reply2
    assert "RMA-AMZ-" in reply2

    # Verify database was mutated ONLY AFTER explicit confirmation
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item["status"] == "returned"
        ret = conn.execute("SELECT * FROM returns WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert ret is not None
        assert ret["reason"] == "damaged"
        assert ret["refund_amount"] == 119.99
    finally:
        conn.close()


def test_rejection_cancels_cleanly_without_mutation():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    # Turn 1: Propose return
    reply1 = wf.handle_turn("I want to return order ORD-9011, item ITEM-9011-1, reason damaged")
    assert wf.state == WorkflowState.WAITING_FOR_CONFIRMATION

    # Turn 2: User declines
    reply2 = wf.handle_turn("No, cancel that")
    assert wf.state == WorkflowState.ACTION_CANCELLED
    assert "cancelled" in reply2.lower()
    assert "No changes have been made" in reply2

    # Verify zero database mutations
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9011-1'").fetchone()
        assert item["status"] == "delivered"
        ret_count = conn.execute("SELECT COUNT(*) FROM returns WHERE line_item_id = 'ITEM-9011-1'").fetchone()[0]
        assert ret_count == 0
    finally:
        conn.close()


def test_q23_missing_parameters_prompts_user_without_inventing():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    reply = wf.handle_turn("start a return for this customer")
    assert wf.state == WorkflowState.CLARIFYING_INPUT
    assert "order ID and specific item ID" in reply

    # Zero database mutations
    conn = get_connection(TEST_DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM returns").fetchone()[0]
        assert count == 2  # Only the 2 seed returns
    finally:
        conn.close()


def test_q24_multi_turn_context_resolution():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    # Turn 1: Operational inquiry about ORD-9021 (Delivered blender)
    reply1 = wf.handle_turn("Can you look up order ORD-9021 and item ITEM-9021-1?")
    assert "ORD-9021" in reply1

    # Turn 2: User refers to previous turn
    reply2 = wf.handle_turn("open a return for the item we just discussed for reason damaged")
    assert wf.state == WorkflowState.WAITING_FOR_CONFIRMATION
    assert "ORD-9021" in reply2
    assert "Ninja Personal Blender" in reply2
    assert "$49.99" in reply2

    # Turn 3: User confirms
    reply3 = wf.handle_turn("Confirm")
    assert wf.state == WorkflowState.ACTION_COMPLETED
    assert "RMA-TGT-" in reply3

    # Verify return created in DB
    conn = get_connection(TEST_DB_PATH)
    try:
        item = conn.execute("SELECT status FROM line_items WHERE line_item_id = 'ITEM-9021-1'").fetchone()
        assert item["status"] == "returned"
    finally:
        conn.close()


def test_q25_loud_refusal_for_already_returned_item():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    # ORD-9033 / ITEM-9033-1 is already returned in RET-702 (status: completed)
    reply = wf.handle_turn("open a return on order ORD-9033 for item ITEM-9033-1 reason defective")
    assert "already been returned" in reply
    assert "RET-702" in reply
    assert "RMA-IKA-702-9033" in reply
    assert "A duplicate return cannot be created" in reply

    # Verify zero extra returns created
    conn = get_connection(TEST_DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM returns WHERE order_id = 'ORD-9033'").fetchone()[0]
        assert count == 1  # Only RET-702
    finally:
        conn.close()


def test_q26_q27_q28_honest_refusals():
    records = RetailRecords(db_path=TEST_DB_PATH)
    wf = ConversationalWorkflow(records=records)

    # Q26: CEO phone number
    reply_q26 = wf.handle_turn("what's the CEO's mobile number?")
    assert "CEO contact information is not in the knowledge base" in reply_q26

    # Q27: Future product price
    reply_q27 = wf.handle_turn("will this product be cheaper next month?")
    assert "cannot predict future pricing" in reply_q27

    # Q28: Non-existent order
    reply_q28 = wf.handle_turn("status of order ORD-99999999?")
    assert "Order ORD-99999999 was not found" in reply_q28
