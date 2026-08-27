#!/usr/bin/env python3
"""Tests for the predicate that authorises a write.

This is the only thing standing between a proposed `create_return` and a real
mutation, and there were two implementations of it — one in `client/loop.py`,
one in `client/workflow.py` — that both asked `any(pattern in text)`. Every
"was executed" case below was measured against those predicates before the fix.

The refusal cases are the important half. A rejection contains an approval as a
substring far more often than English intuition suggests, and the reply is being
typed at the precise moment the user is deciding whether to mutate a record.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for candidate in (REPO_ROOT, REPO_ROOT / "client", REPO_ROOT / "server"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import pytest  # noqa: E402

from client.confirm import is_approval, is_refusal  # noqa: E402
from client.loop import is_confirmed_by_user  # noqa: E402


@pytest.mark.parametrize(
    "reply, contained",
    [
        ("dont do it", "do it"),
        ("stop, do not proceed", "proceed"),
        ("no, thats not ok", "ok"),
        ("no it is ok, cancel that", "ok"),
    ],
)
def test_a_refusal_containing_an_approving_word_does_not_authorise(reply, contained):
    """Each of these executed the write the user had just declined.

    `"dont do it"` is the clearest: the user says don't, and the substring
    matcher finds "do it" and does it.
    """
    assert contained in reply  # the substring that fooled the old matcher
    assert is_refusal(reply)
    assert not is_approval(reply)
    assert not is_confirmed_by_user(reply, None)


@pytest.mark.parametrize(
    "reply",
    [
        "is it ok to return this?",
        "ok so what is the return window?",
        "sure, but first what is the policy?",
        "are we able to proceed with a refund policy question?",
    ],
)
def test_an_ordinary_question_is_not_permission_to_mutate(reply):
    """These are questions, not consent, and every one read as consent before.

    A strong approval now has to OPEN the reply, and a weak one ("ok", "sure")
    has to be essentially the whole reply — a person agreeing types "ok", not
    "ok, and also...".
    """
    assert not is_approval(reply)
    assert not is_confirmed_by_user(reply, None)


@pytest.mark.parametrize(
    "reply",
    ["yes", "yes, go ahead", "confirm", "proceed", "ok", "okay", "go ahead", "do it",
     "yes, open a return for order ORD-9011, item ITEM-9011-1, reason damaged"],
)
def test_real_approvals_still_authorise(reply):
    """Tightening must not break the flow it protects."""
    assert is_approval(reply)
    assert is_confirmed_by_user(reply, None)


@pytest.mark.parametrize("reply", ["نعم", "نعم، تفضل", "موافق", "تمام", "نفذ"])
def test_arabic_approval_is_recognised(reply):
    """The assistant already answers Arabic questions correctly end to end.

    Before this, no Arabic affirmative matched at all, so an Arabic user could
    never approve a write — the feature did not exist for them. It failed
    closed, which is the safe direction, but it was still a dead feature.
    """
    assert is_approval(reply)
    assert is_confirmed_by_user(reply, None)


@pytest.mark.parametrize("reply", ["لا", "لا، الغِ ذلك", "توقف", "no", "cancel", "no thanks"])
def test_refusals_are_refusals_in_both_languages(reply):
    assert is_refusal(reply)
    assert not is_approval(reply)


def test_diacritics_and_alef_variants_do_not_change_the_verdict():
    """Consent must not depend on which keyboard the agent typed it with."""
    assert is_approval("نَعَم")
    assert is_approval("أجل") and is_approval("اجل")


def test_history_cannot_turn_an_ambiguous_reply_into_a_yes():
    """Consent is a property of what the user said, not of what preceded it.

    The old implementation had a second branch that re-matched the same loose
    word list whenever the previous assistant turn mentioned confirmation,
    which is how a maybe becomes a yes.
    """
    history = [{"role": "assistant", "content": "This would call `create_return`. Please confirm."}]
    assert not is_confirmed_by_user("is it ok to return this?", history)
    assert not is_confirmed_by_user("hmm, what happens if I do?", history)
