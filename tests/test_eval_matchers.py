#!/usr/bin/env python3
"""Tests for the scorecard's refusal matchers.

These decide two metrics that pull in opposite directions — "correct refusal"
wants to recognise a no, "false refusal" wants to recognise a withheld answer —
so a pattern that is too loose and one that is too tight both corrupt the
scorecard, in different directions and silently.

They are tested because they were widened, and a matcher widened by the person
being measured by it needs to be pinned. Every positive case below is a verbatim
answer the client actually produced against GB10; every negative case is a
correct answer that must not be mistaken for a refusal.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for candidate in (REPO_ROOT, REPO_ROOT / "eval", REPO_ROOT / "client"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import pytest  # noqa: E402

from client_harness import declined_to_answer, denied_request  # noqa: E402


# Verbatim, from the Q5 run against GB10.
Q5_ANSWER = (
    "The return policy varies by retailer. For Amazon, returns are generally "
    "allowed within 30 days of delivery, while Best Buy allows returns within "
    "15 days. After these periods, returns may not be permitted unless the item "
    "is defective or covered by a warranty."
)

# Verbatim, from the Q28 run against GB10.
Q28_ANSWER = (
    "I couldn't find any information about order ORD-99999999. "
    "Please verify the order number and try again."
)


@pytest.mark.parametrize(
    "answer",
    [
        Q5_ANSWER,
        "That return is not eligible — it is 40 days old and the window is 30.",
        "Returns are not allowed on opened software.",
        "This item may not be allowed back after the window closes.",
        "That item has already been returned under RMA-IKA-702-9033.",
    ],
)
def test_a_grounded_no_counts_as_a_denial(answer):
    """`\\bnot permitted\\b` missed "may not be permitted" over the word "be".

    A denial any reader would call a denial was scored as no refusal at all.
    """
    assert denied_request(answer)


@pytest.mark.parametrize("answer", [Q28_ANSWER, "I didn't find a matching order."])
def test_no_data_phrasing_counts_as_declining(answer):
    """"I couldn't find any information" is a no-data refusal in plain English.

    The existing pattern wanted the literal words "not found".
    """
    assert declined_to_answer(answer)


@pytest.mark.parametrize(
    "answer",
    [
        # The whole point of separating the two matchers: a grounded no is the
        # assistant working, and must never score as a withheld answer.
        "You have 30 days from delivery to return most items [retail: Amazon — Returns].",
        "Order ORD-9021 shipped on 2026-08-14 and was delivered on 2026-08-16.",
        # Near-misses for the widened denial pattern. "not" must not reach
        # across a clause to deny something the sentence was not discussing.
        "Returns are allowed within 30 days, and refunds are not delayed.",
        "The customer is eligible for a refund.",
        "This is permitted under the standard policy.",
    ],
)
def test_a_correct_answer_is_neither_declined_nor_denied(answer):
    """The widening must not turn working answers into refusals.

    "False refusal" is scored from `declined_to_answer` over every non-refusal
    question, so a loose pattern here would invent failures across the set.
    """
    assert not declined_to_answer(answer)
    assert not denied_request(answer)
