#!/usr/bin/env python3
"""Tests for the client-side gates and their helpers.

These functions are load-bearing: they decide whether an answer reaches the
user, which server is asked, and which document is cited. They were added
across several fixes and verified only by throwaway commands at the time, which
is precisely how two regressions reached a commit — a `schema_version` bump that
silently broke `eval/harness.py`, and a `NAME_SEPARATOR` used in `client/loop.py`
without being imported. A check that is not a test does not exist.

Every case here is a real failure that was measured, not a hypothetical, and the
docstrings say which. No chat model and no MCP server is needed: these are pure
functions, so the suite stays fast and runs offline.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for candidate in (REPO_ROOT, REPO_ROOT / "client", REPO_ROOT / "server"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import pytest  # noqa: E402

from client.loop import (  # noqa: E402
    brand_from_records,
    capability_summary,
    classify_tool_type,
    is_composite_question,
    is_comparative_question,
    is_opener,
    is_write_tool,
    search_query_argument,
    servers_matching_question,
)
from client.mcp_client import describe_exception  # noqa: E402
from client.workflow import passage_to_prose  # noqa: E402


@dataclass
class FakeTool:
    """Minimal stand-in for a DiscoveredTool: server, name, description."""

    server: str
    tool_name: str
    description: str

    @property
    def qualified_name(self) -> str:
        return f"{self.server}__{self.tool_name}"


FLEET = [
    FakeTool("retail", "kb_retail_search",
             "Search retail policy and help documentation for returns, delivery, payments"),
    FakeTool("retail", "kb_retail_query_orders",
             "Lookup retail customer order details, dates, fulfillment statuses"),
    FakeTool("banking", "kb_banking_search",
             "Search banking policy and help documentation (disputes, fraud, KYC, bank accounts)"),
    FakeTool("hospitality", "kb_hotel_search",
             "Search hotel booking, cancellation and stay policy documentation"),
]


# --------------------------------------------------------------------------
# Composite detection: needs a policy rule AND an operational record.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "can they return order ORD-9031 — what's the window and is it eligible?",
    "parcel for ORD-9021 split into two — is partial delivery covered, and what shipped?",
    "refund on return RET-701 (order ORD-9031) — how long should it take and did it go through?",
    "I was charged twice — is that allowed and did it actually happen? (customer CUST-101)",
])
def test_composite_questions_are_detected(question):
    """The four eval-set composite questions must all trip the gate.

    Measured before the gate existed: each was answered with a single tool call,
    so composite handling scored 0% — the model took whichever half it noticed
    first and stated it confidently.
    """
    assert is_composite_question(question)


@pytest.mark.parametrize("question", [
    "how long till they get their money back on a return?",   # policy only
    "can they send back opened electronics?",                  # policy only
    "does every store charge a 'restocking fee' on returns?",  # policy only
    "they want to return after 40 days, are we allowed?",      # policy only
    "list open returns for customer CUST-103",                 # record only
    "how much has Marcus Vance (CUST-103) been refunded this year?",  # record only
])
def test_single_sided_questions_do_not_trip_the_composite_gate(question):
    """A pure policy or pure record question must not be forced to fetch both.

    The record markers deliberately require an identifier or a verification
    phrase rather than a bare word like "return", so "money back on a return"
    stays a policy question. A false trigger would spend a round and inflate the
    spurious-call metric on questions that were already answered correctly.
    """
    assert not is_composite_question(question)


# --------------------------------------------------------------------------
# Brand extraction: which retailer's policy applies.
# --------------------------------------------------------------------------

def test_brand_read_from_rma_code_prefix():
    """A returns record has no brand column; the retailer is in the RMA code.

    Measured on Q15: without this, the follow-up search returned IKEA's 365-day
    window for an Amazon order, which would tell an agent a 12-day-old order had
    a year left to return.
    """
    trace = [{"ok": True, "payload": {"results": [{"rma_code": "RMA-AMZ-701-9031"}]}}]
    assert brand_from_records(trace) == "Amazon"


def test_brand_read_from_explicit_field():
    trace = [{"ok": True, "payload": {"results": [{"brand": "bestbuy"}]}}]
    assert brand_from_records(trace) == "Best Buy"


def test_brand_from_shipment_record():
    """`query_shipments` gained a joined `brand` precisely so this works."""
    trace = [{"ok": True, "payload": {"results": [{"shipment_id": "SHIP-402",
                                                   "brand": "target"}]}}]
    assert brand_from_records(trace) == "Target"


@pytest.mark.parametrize("trace", [
    [],                                                                    # nothing ran
    [{"ok": False, "payload": {"results": [{"brand": "target"}]}}],        # failed call
    [{"ok": True, "payload": {"results": [{"rma_code": "RMA-ZZZ-1-2"}]}}],  # unknown code
    [{"ok": True, "payload": {"results": [{"content": "policy text"}]}}],  # no record
])
def test_brand_returns_nothing_it_cannot_prove(trace):
    """Silence beats a guess: a wrong brand is the same bug with an extra step.

    A failed call is ignored too — its payload is an error description, not a
    record, so treating it as evidence would scope a search from a failure.
    """
    assert brand_from_records(trace) == ""


# --------------------------------------------------------------------------
# Comparative detection and peer resolution, both discovery-driven.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected_peer", [
    ("do refund timelines differ between us and the bank?", "banking"),
    ("compare our return window with the hotel's cancellation window", "hospitality"),
])
def test_comparative_questions_resolve_to_the_right_peer(question, expected_peer):
    """"the bank" must find `banking` from its advertised words, not a lookup table.

    Contract v1 §9 makes discovery the rule: peers, names and descriptions all
    arrive at runtime, so a hardcoded map would break silently when a teammate
    renames a server.
    """
    assert is_comparative_question(question)
    assert servers_matching_question(question, FLEET, {"retail"})[0] == expected_peer


@pytest.mark.parametrize("question", [
    "does the bank show a refund for this charge yet?",   # single-domain, not comparative
    "how long till they get their money back on a return?",
    "can they send back opened electronics?",
    "does every store charge a 'restocking fee' on returns?",
])
def test_non_comparative_questions_do_not_trip_the_comparative_gate(question):
    """Q18 routes to banking on its own; forcing a second server would be spurious."""
    assert not is_comparative_question(question)


def test_pure_retail_questions_match_no_peer():
    """No peer should be fetched for a question no peer's vocabulary covers."""
    assert servers_matching_question(
        "how long till they get their money back on a return?", FLEET, {"retail"}
    ) == []


@pytest.mark.parametrize("question", [
    "compare our refund timeline with our delivery timeline",
    "compare Amazon and Target return windows",
    "how do Best Buy and IKEA differ on restocking fees?",
])
def test_intra_retail_comparisons_match_no_peer(question):
    """A word shared with a peer must not drag that peer in.

    Measured false positive: "compare our refund timeline with our delivery
    timeline" is entirely retail, but matched `banking` because banking's own
    description also mentions refunds. A word only identifies a peer when it is
    absent from the home server's vocabulary.
    """
    assert servers_matching_question(question, FLEET, {"retail"}) == []


def test_only_the_strongest_peer_is_chosen():
    """A weakly-overlapping peer must not earn a search of its own.

    "the hotel's cancellation window" scores hospitality on both `hotel` and
    `cancellation`, but telecom also cancels things and scores on `cancellation`
    alone. Calling both would spend a search on a server the question never
    meant.
    """
    fleet = FLEET + [FakeTool("telecom", "kb_telecom_search",
                              "Search telecom policy: billing, plans, disputes, cancellation, roaming")]
    assert servers_matching_question(
        "compare our return window with the hotel's cancellation window",
        fleet, {"retail"},
    ) == ["hospitality"]


def test_a_genuine_two_peer_comparison_returns_both():
    """Tightening to the best match must not break a real multi-way comparison."""
    peers = servers_matching_question(
        "compare the bank and the hotel policies", FLEET, {"retail"}
    )
    assert sorted(peers) == ["banking", "hospitality"]


# --------------------------------------------------------------------------
# Schema-driven argument discovery.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("schema,expected", [
    ({"properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
      "required": ["query"]}, "query"),
    ({"properties": {"q": {"type": "string"}}, "required": ["q"]}, "q"),
    ({"properties": {"text": {"type": "string"}}, "required": ["text"]}, "text"),
    ({"properties": {"search_phrase": {"type": "string"}},
      "required": ["search_phrase"]}, "search_phrase"),
])
def test_query_argument_is_read_from_the_advertised_schema(schema, expected):
    """A teammate's search tool may call it `q` or `text`; assuming `query` fails."""
    assert search_query_argument(schema) == expected


@pytest.mark.parametrize("schema", [
    {"properties": {"top_k": {"type": "integer"}}, "required": ["top_k"]},
    {},
])
def test_no_argument_invented_when_nothing_takes_text(schema):
    """Returning "" makes the caller skip the call rather than fabricate a name."""
    assert search_query_argument(schema) == ""


# --------------------------------------------------------------------------
# Tool classification.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("qualified,expected", [
    ("retail__kb_retail_search", "search"),
    ("banking__kb_banking_search", "search"),
    ("retail__kb_retail_query_orders", "records"),
    ("retail__kb_retail_query_shipments", "records"),
    ("retail__kb_retail_create_return", "write"),
])
def test_tool_types_classified_from_the_name(qualified, expected):
    assert classify_tool_type(qualified) == expected


def test_write_tools_are_recognised_across_servers():
    """The confirmation gate depends on this; a miss here is an unattended write."""
    assert is_write_tool("retail__kb_retail_create_return")
    assert is_write_tool("banking__kb_banking_create_dispute")
    assert not is_write_tool("retail__kb_retail_query_orders")


# --------------------------------------------------------------------------
# Unreachable-server diagnostics.
# --------------------------------------------------------------------------

def test_nested_exception_group_reports_the_real_cause():
    """anyio wraps a refused connection in a group whose own message says nothing.

    The banner previously read "ExceptionGroup: unhandled errors in a TaskGroup
    (1 sub-exception)", naming no host, port or reason.
    """
    try:
        from exceptiongroup import BaseExceptionGroup as Group
    except ImportError:  # Python 3.11+ has it builtin
        Group = BaseExceptionGroup
    inner = ConnectionRefusedError(61, "Connection refused")
    nested = Group("unhandled errors in a TaskGroup", [Group("inner", [inner, inner])])
    described = describe_exception(nested)
    assert "ConnectionRefusedError" in described
    assert "TaskGroup" not in described
    # Identical causes from a retrying transport collapse to one reason.
    assert described.count("ConnectionRefusedError") == 1


def test_plain_exception_is_described_unchanged():
    assert describe_exception(ValueError("bad url")) == "ValueError: bad url"


# --------------------------------------------------------------------------
# Passage flattening for policy-only replies.
# --------------------------------------------------------------------------

def test_headings_and_emphasis_are_stripped_without_changing_words():
    chunk = ("# Best Buy — Return & Exchange Policy\n\n## Standard return window\n"
             "Most products can be returned within **15 days** for a full refund.")
    prose = passage_to_prose(chunk)
    assert prose == "Most products can be returned within 15 days for a full refund."
    assert "#" not in prose and "**" not in prose


def test_list_items_keep_their_own_lines():
    """Flattening a list into a sentence changes what it means."""
    prose = passage_to_prose("# Doc\n## Sec\nIntro.\n\n- First item\n- Second item")
    assert prose.splitlines() == ["Intro.", "- First item", "- Second item"]


def test_headings_only_chunk_falls_back_to_the_original():
    """An empty answer would silently drop the only evidence there was."""
    assert passage_to_prose("# Only headings\n## Nothing else") == \
        "# Only headings\n## Nothing else"


# --------------------------------------------------------------------------
# Openers: a greeting is not a policy question.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "I want a help", "hi", "hello there", "hey", "good morning",
    "what can you do?", "can you help", "help me", "thanks", "", "   ",
])
def test_openers_are_recognised(question):
    """Reported from the running UI: "I want a help" was answered with
    "I don't know — I have no retrieved sources for this, and I won't answer a
    policy question without them." No policy question had been asked, so that
    refusal was both unhelpful and untrue.
    """
    assert is_opener(question)


@pytest.mark.parametrize("question", [
    "can a customer return opened electronics?",
    "status of order ORD-9021?",
    "help me understand the return window",   # says help, asks something real
    "hi, can they return order ORD-9031?",    # greeting plus a real question
    "I need help with a refund",
    "what's the CEO's mobile number?",        # must still reach the refusal path
])
def test_substantive_questions_are_not_treated_as_openers(question):
    """A greeting attached to a real question must not skip retrieval."""
    assert not is_opener(question)


def test_capability_summary_only_advertises_discovered_tools():
    """It must never claim a capability the fleet is not currently serving.

    Built from the live tool list, so a peer being down removes it from the
    reply rather than promising something that cannot be delivered.
    """
    summary = capability_summary(FLEET)
    assert "retail" in summary and "banking" in summary
    assert "search" in summary
    # A server absent from discovery must not appear.
    assert "telecom" not in summary
    retail_only = capability_summary([t for t in FLEET if t.server == "retail"])
    assert "banking" not in retail_only
