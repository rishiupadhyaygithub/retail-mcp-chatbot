#!/usr/bin/env python3
"""Does this reply approve the pending action, refuse it, or neither?

One module because there were two implementations of this question and both got
it wrong the same way — `any(pattern in text)` — and one of them decides whether
a write executes.  Measured against the live predicates:

    "dont do it"                -> contained "do it"    -> CONFIRMED the write
    "stop, do not proceed"      -> contained "proceed"  -> CONFIRMED the write
    "no, thats not ok"          -> contained "ok"       -> CONFIRMED the write
    "no it is ok, cancel that"  -> contained "ok"       -> CONFIRMED the write

Those are the words a person types at exactly the moment they are being asked to
confirm, so this was not a hypothetical.  Substring matching is the whole bug: a
refusal contains an approval as a substring far more often than English
intuition suggests, and `do it` inside `dont do it` is the shape of it.

Three rules replace it, and each exists because a real string broke the old one:

1. A negation ANYWHERE makes the reply a refusal, whatever else it contains.
   Failing closed is the only safe direction for a gate that authorises a
   mutation — the cost of missing a yes is one more question, and the cost of
   missing a no is a return the customer did not ask for.
2. A strong approval ("yes", "confirm", "proceed") counts only when the reply
   OPENS with it.  "are we able to proceed with a policy question?" is not
   permission to write.
3. A weak approval ("ok", "sure") counts only when it is essentially the whole
   reply.  "ok so what is the return window?" opens with one and approves
   nothing; a person agreeing types "ok", not "ok, and also...".

Arabic is included because the assistant already answers Arabic questions
correctly end to end, and a gate that only recognises English consent is a
feature that silently does not exist for those users.  It fails closed there
too: before this, no Arabic affirmative matched at all, so an Arabic user could
never approve a write.
"""
from __future__ import annotations

import re
import unicodedata

# A refusal anywhere in the reply wins. Includes the fragments that made the old
# matcher invert a rejection: "dont", "not", "stop".
NEGATIONS = (
    # English
    "no", "nope", "nah", "not", "dont", "don't", "do not", "cancel", "stop",
    "abort", "reject", "decline", "never", "nevermind", "wait", "hold",
    # Arabic
    "لا", "كلا", "ليس", "الغ", "الغاء", "إلغاء", "توقف", "ارفض", "انتظر",
)

# Unambiguous approval. Must OPEN the reply.
STRONG_AFFIRMATIVES = (
    # English
    "yes", "yep", "yeah", "yup", "confirm", "confirmed", "confirmi",
    "proceed", "approved", "approve", "execute", "affirmative",
    "go ahead", "do it", "please proceed", "yes please",
    # Arabic
    "نعم", "اجل", "موافق", "اوافق", "موافقة", "تفضل", "نفذ", "اكيد", "بالتاكيد",
)

# Approval only when it is the entire reply. These words appear constantly
# inside ordinary questions ("is it ok to..."), which is how they leaked.
WEAK_AFFIRMATIVES = (
    "ok", "okay", "k", "sure", "fine", "alright", "right",
    "تمام", "حسنا", "طيب", "ماشي",
)

_MAX_WEAK_TOKENS = 2

# Arabic diacritics and tatweel carry no consent information and vary by
# keyboard, so they are stripped before matching rather than enumerated.
_ARABIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟـ]")
_ALEF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})


def normalise(text: str) -> str:
    """Lowercase, strip Arabic diacritics, and fold alef/ta-marbuta variants."""
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = _ARABIC_MARKS.sub("", folded)
    return folded.translate(_ALEF_VARIANTS)


def _tokens(text: str) -> list[str]:
    # Apostrophes stay inside a token so "don't" survives as one word; Arabic
    # comma and question mark are separators like their ASCII counterparts.
    return [t for t in re.split(r"[^\w']+", normalise(text), flags=re.UNICODE) if t]


def is_refusal(text: str) -> bool:
    """True when the reply contains a refusal anywhere in it."""
    toks = _tokens(text)
    joined = " ".join(toks)
    if any(t in NEGATIONS for t in toks):
        return True
    # Multi-word negations and Arabic prefixed forms ("الغِ" -> "الغ").
    return any(" " in n and n in joined for n in NEGATIONS) or any(
        t.startswith("الغ") for t in toks
    )


def is_approval(text: str) -> bool:
    """True only for a reply that actually grants permission.

    Refusal is checked first and wins outright, so a reply that both refuses and
    happens to contain an approving word is a refusal.
    """
    toks = _tokens(text)
    if not toks or is_refusal(text):
        return False

    joined = " ".join(toks)
    for phrase in STRONG_AFFIRMATIVES:
        # Opens with it — as the first word, or the first words for "go ahead".
        if joined == phrase or joined.startswith(phrase + " "):
            return True

    if len(toks) <= _MAX_WEAK_TOKENS and all(
        t in WEAK_AFFIRMATIVES or t in STRONG_AFFIRMATIVES for t in toks
    ):
        return True

    return False
