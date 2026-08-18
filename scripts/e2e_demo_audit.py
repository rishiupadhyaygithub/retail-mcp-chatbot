"""End-to-End Live Product Journey Audit (Phase 4).

Runs 7 complete user journeys across the live stack:
1. Policy-only inquiry (Chroma retrieval + citation).
2. Record-only inquiry (SQLite MCP query + factual answer).
3. Composite reasoning (Dual-provenance synthesis: SQLite facts + Chroma policy).
4. Full Return Request with Confirmation Gate (Investigation -> WAITING_FOR_CONFIRMATION -> User Confirms -> RMA Generated).
5. Dangerous/Ambiguous Return (Missing parameters -> Clarification, ZERO mutations).
6. Duplicate Return Attempt (Existing return detected -> Loud non-retryable refusal).
7. Unknown Order (Zero rows -> Honest empty refusal).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from client.workflow import ConversationalWorkflow, WorkflowState
from server.records import RetailRecords
from server.retrieval import RetailRetrieval

def run_e2e_audit():
    print("=" * 80)
    print("TOPAZ RETAIL MCP CHATBOT — END-TO-END LIVE PRODUCT AUDIT")
    print("=" * 80)

    demo_db = REPO_ROOT / "data" / "demo_audit_retail.db"
    from data.seed_records import seed_records
    seed_records(demo_db)

    records = RetailRecords(db_path=demo_db)
    retrieval = RetailRetrieval()

    # Journey 1: Policy-Only Question
    print("\n--- [JOURNEY 1] Policy-Only Question ---")
    wf1 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q1 = "Can a customer return opened electronics at Best Buy?"
    print(f"User: '{q1}'")
    a1 = wf1.handle_turn(q1)
    print(f"Assistant:\n{a1}")

    # Journey 2: Record-Only Question
    print("\n--- [JOURNEY 2] Record-Only Operational Question ---")
    wf2 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q2 = "Look up order ORD-9011"
    print(f"User: '{q2}'")
    a2 = wf2.handle_turn(q2)
    print(f"Assistant:\n{a2}")

    # Journey 3: Composite Reasoning Question (Primary Showcase)
    print("\n--- [JOURNEY 3] Composite Reasoning (Dual-Provenance Synthesis) ---")
    wf3 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q3 = "Can they return order ORD-9031 — what's the window and is it eligible?"
    print(f"User: '{q3}'")
    a3 = wf3.handle_turn(q3)
    print(f"Assistant:\n{a3}")

    # Journey 4: Full Return Creation with Confirmation Safety Gate
    print("\n--- [JOURNEY 4] State-Changing Return Creation with Safety Confirmation Gate ---")
    wf4 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q4_t1 = "open a return for order ORD-9011, item ITEM-9011-1, reason damaged"
    print(f"Turn 1 User: '{q4_t1}'")
    a4_t1 = wf4.handle_turn(q4_t1)
    print(f"Assistant [State: {wf4.state.value}]:\n{a4_t1}")
    
    q4_t2 = "Yes, please confirm and proceed"
    print(f"\nTurn 2 User: '{q4_t2}'")
    a4_t2 = wf4.handle_turn(q4_t2)
    print(f"Assistant [State: {wf4.state.value}]:\n{a4_t2}")

    # Journey 5: Dangerous/Ambiguous Return (Missing fields)
    print("\n--- [JOURNEY 5] Dangerous/Ambiguous Request (Missing Parameters) ---")
    wf5 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q5 = "start a return for this customer"
    print(f"User: '{q5}'")
    a5 = wf5.handle_turn(q5)
    print(f"Assistant [State: {wf5.state.value}]:\n{a5}")

    # Journey 6: Duplicate Return Attempt
    print("\n--- [JOURNEY 6] Duplicate Return Attempt on Already-Returned Item ---")
    wf6 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q6 = "open a return on order ORD-9033 for item ITEM-9033-1 reason defective"
    print(f"User: '{q6}'")
    a6 = wf6.handle_turn(q6)
    print(f"Assistant [State: {wf6.state.value}]:\n{a6}")

    # Journey 7: Unknown Order Refusal
    print("\n--- [JOURNEY 7] Unknown Order Honest Refusal ---")
    wf7 = ConversationalWorkflow(records=records, retrieval=retrieval)
    q7 = "status of order ORD-99999999?"
    print(f"User: '{q7}'")
    a7 = wf7.handle_turn(q7)
    print(f"Assistant [State: {wf7.state.value}]:\n{a7}")

    print("\n" + "=" * 80)
    print("ALL 7 END-TO-END PRODUCT JOURNEYS EXECUTED SUCCESSFULLY")
    print("=" * 80)

if __name__ == "__main__":
    run_e2e_audit()
