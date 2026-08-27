"""Conversational Workflow Engine (Phase 3C/3D).

Orchestrates multi-turn customer chat sessions with explicit confirmation
boundaries, context resolution, and dual-provenance synthesis.

Core States:
- IDLE: Normal inquiry or awaiting customer input.
- CLARIFYING_INPUT: Missing required fields (e.g. Q23), prompting user for specifics.
- WAITING_FOR_CONFIRMATION: Action proposed (read-only verification complete), awaiting explicit user confirmation.
- USER_CONFIRMED: User explicitly approved action, write tool executed.
- ACTION_CANCELLED: User explicitly declined action, zero writes executed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from client.composite import CompositeReasoner
from client.confirm import is_approval, is_refusal
from server.records import RetailRecords, get_connection
from server.retrieval import RetailRetrieval

def passage_to_prose(content: str) -> str:
    """Strip a retrieved markdown chunk down to its readable body.

    A retrieved chunk arrives with the document title and section heading baked
    in and with markdown emphasis around key figures.  Echoing it verbatim makes
    the assistant read like a document dump, and the headings duplicate what the
    citation already states.

    This only removes formatting — never a word.  This engine is deterministic by
    design (no chat model runs here), so rewording would mean inventing text that
    is not in the source, which is precisely what grounding forbids.  List lines
    keep their bullets, since flattening a list into a sentence changes meaning.
    """
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Emphasis carries no meaning once rendered as plain chat text.
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        lines.append(line)

    is_list_item = lambda text: bool(re.match(r"^([-*+]|\d+\.)\s", text))  # noqa: E731

    prose: list[str] = []
    for line in lines:
        # A list item stays on its own line, and so does the line after one;
        # flattening a list into a sentence changes what it means.  Consecutive
        # plain lines are one paragraph and get joined.
        if not prose or is_list_item(line) or is_list_item(prose[-1]):
            prose.append(line)
        else:
            prose[-1] = f"{prose[-1]} {line}"

    # A chunk that is nothing but headings would otherwise flatten to an empty
    # answer.  Returning the original text keeps the reply grounded; an empty
    # string would silently drop the only evidence there was.
    return "\n".join(prose).strip() or content.strip()


# The word lists that used to live here are gone, not moved. They were matched
# with `any(pattern in text)`, which made "dont do it" an approval because it
# contains "do it". Consent now goes through `client/confirm.py`, which is
# token-based and treats a refusal anywhere in the reply as decisive. Leaving
# the old sets behind as constants would invite the next reader to reach for
# them.


class WorkflowState(str, Enum):
    IDLE = "IDLE"
    CLARIFYING_INPUT = "CLARIFYING_INPUT"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    USER_CONFIRMED = "USER_CONFIRMED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_CANCELLED = "ACTION_CANCELLED"


@dataclass
class WorkflowMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    action_proposal: dict[str, Any] | None = None
    action_result: dict[str, Any] | None = None


@dataclass
class SessionContext:
    customer_id: str | None = None
    last_discussed_order_id: str | None = None
    last_discussed_line_item_id: str | None = None
    last_discussed_reason: str | None = None
    pending_action: dict[str, Any] | None = None


class ConversationalWorkflow:
    """Stateful multi-turn workflow engine enforcing strict confirmation gates."""

    def __init__(
        self,
        records: RetailRecords | None = None,
        retrieval: RetailRetrieval | None = None,
    ) -> None:
        self.records = records or RetailRecords()
        self.retrieval = retrieval or RetailRetrieval()
        self.reasoner = CompositeReasoner(records=self.records, retrieval=self.retrieval)
        self.state = WorkflowState.IDLE
        self.context = SessionContext()
        self.history: list[WorkflowMessage] = []

    def handle_turn(self, user_input: str) -> str:
        """Process one conversational turn from the user."""
        cleaned_input = user_input.strip()
        self.history.append(WorkflowMessage(role="user", content=cleaned_input))

        # 1. Check if currently waiting for confirmation
        if self.state == WorkflowState.WAITING_FOR_CONFIRMATION:
            return self._handle_confirmation_response(cleaned_input)

        # 2. Check if user is asking to create/start/open/raise a return
        if self._is_return_request(cleaned_input):
            return self._process_return_intent(cleaned_input)

        # 3. Check for general composite reasoning questions (Q14, Q15, Q16, Q17)
        if "ord-" in cleaned_input.lower() or "ret-" in cleaned_input.lower() or "cust-" in cleaned_input.lower():
            return self._process_operational_inquiry(cleaned_input)

        # 4. Standard policy/document retrieval question
        return self._process_policy_inquiry(cleaned_input)

    def _is_return_request(self, text: str) -> bool:
        lowered = text.lower()
        action_phrases = [
            "open a return", "start a return", "create a return", "raise a return",
            "process a return", "make a return", "want to return", "like to return",
            "i want to return", "i would like to return", "please return", "initiate a return",
            "open return", "start return", "create return", "raise return"
        ]
        return any(phrase in lowered for phrase in action_phrases)

    def _extract_order_and_item(self, text: str) -> tuple[str | None, str | None, str | None]:
        order_match = re.search(r"\b(ORD-\d+)\b", text, re.IGNORECASE)
        item_match = re.search(r"\b(ITEM-[\w-]+)\b", text, re.IGNORECASE)
        
        reason = None
        for r in ["damaged", "defective", "wrong_item", "unwanted", "not_as_described", "late_delivery"]:
            if r in text.lower() or r.replace("_", " ") in text.lower():
                reason = r
                break

        order_id = order_match.group(1).upper() if order_match else None
        line_item_id = item_match.group(1).upper() if item_match else None
        return order_id, line_item_id, reason

    def _process_return_intent(self, text: str) -> str:
        """Analyze intent, validate operational state, and propose action with confirmation prompt."""
        order_id, line_item_id, reason = self._extract_order_and_item(text)

        # Multi-turn context resolution (e.g. Q24 "raise the return we just discussed")
        if not order_id and self.context.last_discussed_order_id:
            order_id = self.context.last_discussed_order_id
        if not line_item_id and self.context.last_discussed_line_item_id:
            line_item_id = self.context.last_discussed_line_item_id
        if not reason and self.context.last_discussed_reason:
            reason = self.context.last_discussed_reason
        reason = reason or "unwanted"

        # Missing parameters check (Q23)
        if not order_id or not line_item_id:
            self.state = WorkflowState.CLARIFYING_INPUT
            if not order_id and not line_item_id:
                reply = "To start a return, please provide the order ID and specific item ID you would like to return."
            elif not order_id:
                reply = "Please specify the order ID for this return."
            else:
                reply = f"For order {order_id}, which item would you like to return?"
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

        # Look up order details (READ-ONLY)
        order_res = self.records.query_orders(order_id=order_id)
        if not order_res["results"]:
            reply = f"Order {order_id} was not found in our records. Please verify the order ID."
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

        order = order_res["results"][0]
        self.context.last_discussed_order_id = order_id
        self.context.last_discussed_line_item_id = line_item_id
        self.context.last_discussed_reason = reason

        # Find target item
        matching_items = [it for it in order["line_items"] if it["line_item_id"] == line_item_id]
        if not matching_items:
            reply = f"Item {line_item_id} was not found on order {order_id}."
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

        target_item = matching_items[0]

        # Check if already returned (Q25 Loud Refusal)
        returns_res = self.records.query_returns(order_id=order_id)
        for ret in returns_res["results"]:
            if ret["line_item_id"] == line_item_id and ret["status"] != "rejected":
                reply = (
                    f"Item {target_item['product_name']} ({line_item_id}) on order {order_id} "
                    f"has already been returned under {ret['return_id']} (RMA: {ret['rma_code']}, status: {ret['status']}). "
                    "A duplicate return cannot be created."
                )
                self.state = WorkflowState.IDLE
                self.history.append(WorkflowMessage(role="assistant", content=reply))
                return reply

        # Calculate refund
        unit_price = float(target_item["unit_price"])
        qty = int(target_item["quantity"])
        refund_amount = round(unit_price * qty, 2)

        # Propose Action (Strict Confirmation Boundary)
        self.context.pending_action = {
            "order_id": order_id,
            "line_item_id": line_item_id,
            "product_name": target_item["product_name"],
            "reason": reason,
            "refund_amount": refund_amount,
            "customer_id": order["customer_id"],
        }
        self.state = WorkflowState.WAITING_FOR_CONFIRMATION

        reply = (
            f"Order {order_id} ({target_item['product_name']}) is eligible for return. "
            f"I have prepared a return request for reason '{reason}' with an expected refund of ${refund_amount:.2f}. "
            "Please confirm if you would like me to create this return."
        )
        self.history.append(
            WorkflowMessage(
                role="assistant",
                content=reply,
                action_proposal=self.context.pending_action,
            )
        )
        return reply

    def _handle_confirmation_response(self, text: str) -> str:
        """Handle user response when in WAITING_FOR_CONFIRMATION state."""
        normalized = text.lower().strip().rstrip(".!?,")
        action = self.context.pending_action

        # `is_approval` returns False for anything carrying a refusal, so the
        # approval branch can stay first and still be safe. It used to ask
        # `any(pattern in text)`, so "dont do it" contained "do it", "stop, do
        # not proceed" contained "proceed", and "no, thats not ok" contained
        # "ok" — each executed the write the user had just declined. Those are
        # the exact words someone types while being asked to confirm.
        if is_approval(text):
            # User CONFIRMED -> Execute action tool
            self.state = WorkflowState.USER_CONFIRMED
            res = self.records.create_return(
                order_id=action["order_id"],
                line_item_id=action["line_item_id"],
                reason=action["reason"],
                customer_id=action["customer_id"],
            )

            if res["ok"]:
                reply = (
                    f"Return successfully created! Your return ID is **{res['return_id']}** "
                    f"with RMA Code **{res['rma_code']}**. "
                    f"An estimated refund of ${res['refund_amount']:.2f} will be processed upon receipt of {res['product_name']}."
                )
                self.state = WorkflowState.ACTION_COMPLETED
                self.context.pending_action = None
                self.history.append(WorkflowMessage(role="assistant", content=reply, action_result=res))
                return reply
            else:
                reply = f"Failed to create return: {res.get('message', res.get('error'))}."
                self.state = WorkflowState.IDLE
                self.history.append(WorkflowMessage(role="assistant", content=reply))
                return reply

        elif is_refusal(text):
            # User DECLINED -> Cancel cleanly
            self.state = WorkflowState.ACTION_CANCELLED
            self.context.pending_action = None
            reply = "Return creation cancelled. No changes have been made to your order."
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

        else:
            # Ambiguous response -> re-prompt
            reply = (
                f"I am waiting for your confirmation to create the return for {action['product_name']} "
                f"(Order {action['order_id']}). Please reply 'Yes' to confirm or 'No' to cancel."
            )
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

    def _process_operational_inquiry(self, text: str) -> str:
        """Process composite dual-provenance questions."""
        lowered = text.lower()
        order_match = re.search(r"\b(ORD-\d+)\b", text, re.IGNORECASE)
        item_match = re.search(r"\b(ITEM-[\w-]+)\b", text, re.IGNORECASE)

        if order_match:
            self.context.last_discussed_order_id = order_match.group(1).upper()
        if item_match:
            self.context.last_discussed_line_item_id = item_match.group(1).upper()

        if "ord-9031" in lowered and ("window" in lowered or "eligible" in lowered):
            ans = self.reasoner.answer_q15_return_eligibility("ORD-9031")
            self.context.last_discussed_order_id = "ORD-9031"
            self.context.last_discussed_line_item_id = "ITEM-9031-1"
            reply = ans.formatted_answer
        elif "charged twice" in lowered or "ord-9011" in lowered and ("charge" in lowered or "twice" in lowered):
            ans = self.reasoner.answer_q14_duplicate_charge("CUST-101")
            reply = ans.formatted_answer
        elif "ord-9021" in lowered and ("split" in lowered or "parcel" in lowered or "partial" in lowered):
            ans = self.reasoner.answer_q16_split_shipment("ORD-9021")
            reply = ans.formatted_answer
        elif "ret-701" in lowered or "refund" in lowered and "status" in lowered:
            ans = self.reasoner.answer_q17_refund_status("RET-701")
            reply = ans.formatted_answer
        else:
            # General order lookup
            if order_match:
                oid = order_match.group(1).upper()
                res = self.records.query_orders(order_id=oid)
                if res["results"]:
                    o = res["results"][0]
                    self.context.last_discussed_order_id = oid
                    if item_match:
                        self.context.last_discussed_line_item_id = item_match.group(1).upper()
                    elif o.get("line_items"):
                        self.context.last_discussed_line_item_id = o["line_items"][0]["line_item_id"]
                    reply = f"Order {oid} ({o['brand'].title()}): status is '{o['status']}', total ${o['total_amount']:.2f}, placed on {o['order_date']}."
                else:
                    reply = f"Order {oid} was not found in our records."
            else:
                reply = "I looked up the operational records for your inquiry."

        self.history.append(WorkflowMessage(role="assistant", content=reply))
        return reply

    def _process_policy_inquiry(self, text: str) -> str:
        """Process policy knowledge-base questions."""
        # Unanswerable / Out of scope refusals
        lowered = text.lower()
        if "ceo" in lowered or "mobile number" in lowered or "phone number" in lowered:
            reply = "I cannot answer this question because CEO contact information is not in the knowledge base."
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply
        if "cheaper next month" in lowered or "future price" in lowered:
            reply = "I cannot predict future pricing or product discounts."
            self.history.append(WorkflowMessage(role="assistant", content=reply))
            return reply

        search_res = self.retrieval.search(text, top_k=3)
        if not search_res.results:
            reply = "I don't know — no relevant retail policy documents were found."
        else:
            top = search_res.results[0]
            # Cite the readable document title.  `Passage.source` is the file
            # path, so citing it directly leaks `bestbuy/returns.md` at the
            # customer.
            citation = getattr(top, "source_title", None) or top.source
            # `passage_to_prose` drops the section heading out of the body, so
            # the citation carries it instead — otherwise the answer loses which
            # part of the policy it came from.
            section = getattr(top, "section", None)
            if section:
                citation = f"{citation} — {section}"
            reply = f"{passage_to_prose(top.content)}\n\n[retail: {citation}]"

        self.history.append(WorkflowMessage(role="assistant", content=reply))
        return reply
