#!/usr/bin/env python3
"""The client's tool-call loop: the only place reasoning happens.

Design document §5.  One turn is:

    build prompt (system rules + history + every discovered tool)
      -> ask the chat model
      -> did it request tools?  run them in parallel, feed results back
      -> repeat, capped at MAX_ROUNDS
      -> otherwise the model's text is the answer

The cap is what stops a confused model spinning.  Every round is recorded in a
trace so the UI can show exactly which tool ran with which arguments and what
came back — the answer alone is not enough to tell a retrieval failure from a
routing failure from the model ignoring good passages, and the scorecard scores
those layers separately.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from openai import OpenAI

from mcp_client import NAME_SEPARATOR, MCPFleet, ToolOutcome, load_server_configs

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt_v3.md"
PROMPT_VERSION = "v3"

# Design doc §5.  Five is enough for a cross-server comparison (one search per
# server plus a synthesis round) and short enough that a loop costs seconds.
MAX_ROUNDS = 5

# The chat model is served by vLLM on the GB10 box behind an OpenAI-compatible
# API.  Nothing here is hardcoded past a default: the platform document is
# explicit that the endpoint may be re-provisioned and that model names belong in
# config, so every value below is an environment override and the base URL is
# read on the server side only — it must never reach browser JavaScript.
DEFAULT_MODEL = os.environ.get("CHAT_MODEL", "topaz-coder")
CHAT_BASE_URL = os.environ.get("CHAT_BASE_URL", "http://dev.topaztel.ae:15124/v1")
# vLLM has no auth on this route; the SDK still requires the field to be set.
CHAT_API_KEY = os.environ.get("CHAT_API_KEY", "not-needed")

# Ollama defaulted to 0.8, the OpenAI API defaults to 1.0.  Migrating without
# pinning this would silently raise sampling temperature on the exact axis the
# eval set measures — fabricated citations and language drift.  0.3 is the value
# the platform document itself recommends for retrieval-grounded answering.
CHAT_TEMPERATURE = float(os.environ.get("CHAT_TEMPERATURE", "0.3"))
# An agent reads the answer aloud on a live call; anything past a few hundred
# tokens is already too long to be read out, and an unbounded generation on a
# shared box with no per-user quota is how one loop saturates it for everyone.
CHAT_MAX_TOKENS = int(os.environ.get("CHAT_MAX_TOKENS", "512"))
# Wall-clock ceiling per model call.  MAX_ROUNDS of these is the worst case a
# turn can cost, so this is the number that bounds a hung endpoint.
CHAT_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TIMEOUT", "60"))

# Phase 1 exposes no write tools, but the confirmation gate ships now rather
# than being retrofitted in phase 3 next to the first tool that can actually
# mutate a record.  A tool is treated as a write until proven otherwise when its
# name starts with one of these verbs; the contract's phase-3 revision is
# expected to mark writes explicitly, at which point this heuristic is replaced.
WRITE_VERBS = ("create_", "open_", "cancel_", "update_", "delete_", "submit_", "raise_")

# A composite question needs a policy document AND an operational record in one
# answer: "is that allowed" is a rule, "did it actually happen" is a row.
# Measured on the 28-question eval set: the model answered all four composite
# questions with a single tool call, so composite handling scored 0%.  It picks
# whichever half it noticed first and then answers confidently from that half
# alone, which reads as complete and is not.
#
# The markers stay deliberately narrow so a pure-policy or pure-record question
# never trips the gate.  In particular the record markers require a specific
# identifier or a verification phrase, never a bare word like "return", so
# Q1 ("how long till they get their money back on a return?") stays a policy
# question and Q12 ("how much has this customer been refunded") stays a record
# question.
POLICY_INTENT = (
    "policy", "allowed", "permitted", "eligible", "eligibility", "window",
    "covered", "entitled", "supposed to", "how long", "rule", "are we able",
)
RECORD_INTENT = (
    "ord-", "ret-", "item-", "cust-", "ship-", "rma-",
    "did it", "actually happen", "did that happen", "went through",
    "has it", "was it", "status of",
)


def is_composite_question(question: str) -> bool:
    """True when one answer needs both a policy rule and an operational record."""
    low = question.lower()
    return any(m in low for m in POLICY_INTENT) and any(m in low for m in RECORD_INTENT)


# Inverse of the brand code map in `server/records.py` (the `brand_map` used to
# mint RMA codes).  Needed because a returns record carries `rma_code`
# ("RMA-AMZ-701-9031") but no `brand` column, so the retailer is only
# recoverable from the code.  Mirrored rather than imported: the client must not
# depend on a server module, and contract v1 keeps them separately deployable.
# If a brand is added server-side without updating this, the effect is a missing
# hint, never a wrong one — `brand_from_records` returns nothing it cannot prove.
RMA_BRAND_CODES = {"AMZ": "Amazon", "BBY": "Best Buy", "TGT": "Target", "IKA": "IKEA"}

BRAND_NAMES = {
    "amazon": "Amazon", "bestbuy": "Best Buy", "best buy": "Best Buy",
    "target": "Target", "ikea": "IKEA",
}


def brand_from_records(trace: list[dict[str, Any]]) -> str:
    """The retailer named by any record already retrieved this turn, if any.

    Policies genuinely conflict across these four retailers — 30 days at Amazon
    against 365 at IKEA — so searching without the brand is not merely vague, it
    returns a confidently wrong window.  Measured on Q15: the record identified
    an Amazon order and the follow-up search returned IKEA's 365-day policy,
    which would tell an agent a 12-day-old order had a year to run.

    Only what a record actually stated is returned; nothing is inferred from the
    question text, because a guessed brand would be the same failure with an
    extra step.
    """
    def walk(node: Any) -> str:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "brand" and isinstance(value, str):
                    found = BRAND_NAMES.get(value.strip().lower())
                    if found:
                        return found
                if key == "rma_code" and isinstance(value, str):
                    parts = value.split("-")
                    if len(parts) > 1 and parts[1].upper() in RMA_BRAND_CODES:
                        return RMA_BRAND_CODES[parts[1].upper()]
                nested = walk(value)
                if nested:
                    return nested
        elif isinstance(node, list):
            for item in node:
                nested = walk(item)
                if nested:
                    return nested
        return ""

    for event in trace:
        if event.get("ok"):
            brand = walk(event.get("payload"))
            if brand:
                return brand
    return ""


# A comparative question asks how two industries differ, so answering it from
# one server is not a partial answer — it is a comparison with nothing to
# compare against.  Measured on Q20 ("do refund timelines differ between us and
# the bank?"): the model searched retail only and presented retail's timeline as
# the answer, so cross-server synthesis scored 0%.
COMPARATIVE_MARKERS = (
    "differ", "difference", "compare", "compared", "comparison", "versus", " vs ",
    "same as", "than ours", "than we", "between us and", "both",
)

# Words too common to identify an industry.  Kept small: the test is whether a
# word appears in another server's own advertised vocabulary, so ordinary
# question words mostly fail that test anyway.
_STOPWORDS = frozenset({
    "does", "differ", "different", "difference", "between", "compare", "compared",
    "comparison", "about", "with", "from", "what", "when", "which", "their",
    "there", "this", "that", "these", "those", "have", "has", "our", "ours",
    "us", "we", "the", "and", "for", "yet", "how", "long", "take", "than",
    "same", "both", "versus", "policy", "policies", "customer", "please",
})


# An opener like "hi" or "I want a help" is not a question with an answer to
# ground.  The grounding gate treats any answer with no tool behind it as a
# fabrication risk, which is right for "what is the return window" and wrong
# here: it met a person saying hello with
# "I don't know — I have no retrieved sources for this, and I won't answer a
# policy question without them."  That is a dead end for the one user who most
# needs guidance, and it is not even accurate, because no policy question was
# asked.
OPENER_PATTERNS = (
    r"^(hi|hey|hello|yo|hiya)\b",
    r"^(good )?(morning|afternoon|evening)\b",
    r"\bhelp me\b", r"\bi (want|need) (a |some )?help\b", r"\bcan you help\b",
    r"\bwhat can you do\b", r"\bwho are you\b", r"\bhow do (i|you) (start|work)\b",
    r"^(thanks|thank you|ok|okay|cool|got it)\b",
    r"^\W*$",
)

# If any of these appear, the user is asking something substantive even if they
# also said hello, so the normal loop runs and the gates apply as usual.
SUBSTANTIVE_MARKERS = POLICY_INTENT + RECORD_INTENT + (
    "return", "refund", "order", "ship", "deliver", "warranty", "cancel",
    "charge", "track", "exchange", "fee", "dispute", "account",
)


def is_opener(question: str) -> bool:
    """True for a greeting or a bare request for help, with nothing to look up."""
    low = question.strip().lower()
    if len(low) > 120:
        return False
    if any(m in low for m in SUBSTANTIVE_MARKERS):
        return False
    return any(re.search(p, low) for p in OPENER_PATTERNS)


def capability_summary(tools: list[Any]) -> str:
    """What this assistant can do, described from what was actually discovered.

    Built from the live tool list rather than a written-out sentence, so it can
    never advertise a capability the fleet is not currently serving — including
    when a peer server is down and its tools are absent.
    """
    by_server: dict[str, list[str]] = {}
    for tool in tools:
        bare = tool.tool_name
        for prefix in ("kb_",):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
        bare = bare.replace(f"{tool.server}_", "", 1).replace("_", " ")
        by_server.setdefault(tool.server, []).append(bare)

    lines = [
        "I answer questions about published policies and the operational records "
        "behind them, and every answer is grounded in a source I retrieve first.",
        "",
        "Right now I can reach:",
    ]
    for server, names in sorted(by_server.items()):
        lines.append(f"  • {server}: {', '.join(sorted(names))}")
    lines += [
        "",
        "Ask me something specific and I will go and look it up. For example:",
        "  • \"can a customer return opened electronics at Best Buy?\"",
        "  • \"what's the status of order ORD-9021?\"",
        "  • \"can they return order ORD-9031 — what's the window and is it eligible?\"",
    ]
    return "\n".join(lines)


def is_comparative_question(question: str) -> bool:
    low = f" {question.lower()} "
    return any(m in low for m in COMPARATIVE_MARKERS)


def servers_matching_question(
    question: str, tools: list[Any], exclude: set[str]
) -> list[str]:
    """Servers whose own advertised vocabulary the question uses.

    Matched against each server's name and tool descriptions rather than a
    hardcoded "bank means the banking server" table, because contract v1 §9
    makes discovery the rule: the set of peers, their names and their wording all
    come from `servers.json` and `tools/list` at runtime.  A teammate renaming a
    server or rewording a description keeps working; a lookup table would not.

    Substring matching is deliberate so "bank" finds the `banking` server. Ranked
    by how many distinct question words a server accounts for, so the best match
    comes first and the caller can bound how many extra calls it makes.
    """
    blobs: dict[str, str] = {}
    home = ""
    for tool in tools:
        text = " " + (tool.server + " " + (tool.description or "")).lower()
        if tool.server in exclude:
            home += text
            continue
        blobs.setdefault(tool.server, "")
        blobs[tool.server] += text

    words = {
        w for w in re.findall(r"[a-z]{4,}", question.lower()) if w not in _STOPWORDS
    }
    # A word only identifies a peer if it is DISTINCTIVE to that peer — present
    # in its vocabulary and absent from the home server's. Domains share plenty
    # of vocabulary, and counting shared words matched "compare our refund
    # timeline with our delivery timeline" (entirely retail) to the banking
    # server, because banking's description also mentions refunds. That would
    # have fired a spurious cross-server search on a question one server fully
    # answers.
    scored = [
        (sum(1 for w in words if w in blob and w not in home), server)
        for server, blob in blobs.items()
    ]
    best = max((score for score, _ in scored), default=0)
    if best == 0:
        return []
    # Only the strongest match, or a genuine tie. "compare our return window with
    # the hotel's cancellation window" scores hospitality 2 (hotel, cancellation)
    # and telecom 1 (cancellation alone, since telecom also cancels things), and
    # calling both would spend a search on a server the question never meant. A
    # real three-way comparison still ties and still returns every side.
    return [server for score, server in sorted(scored, reverse=True) if score == best]


def search_query_argument(input_schema: dict[str, Any]) -> str:
    """The name of a search tool's free-text query parameter, from its schema.

    Read from the advertised schema rather than assumed to be `query`, because
    contract v1 §9 makes runtime discovery the rule: a teammate may call it `q`
    or `text`. Falls back to the first required string property, then to the
    first string property, and returns "" when nothing plausibly takes text —
    at which point the caller must not invent an argument name.
    """
    properties = input_schema.get("properties") or {}
    required = [r for r in (input_schema.get("required") or []) if r in properties]

    def is_text(name: str) -> bool:
        return (properties.get(name) or {}).get("type") in (None, "string")

    for candidate in ("query", "q", "text", "search", "question"):
        if candidate in properties and is_text(candidate):
            return candidate
    for name in required:
        if is_text(name):
            return name
    for name in properties:
        if is_text(name):
            return name
    return ""


def classify_tool_type(qualified_name: str) -> str:
    """`search` for document retrieval, `records` for structured lookups.

    Derived from the advertised name rather than a hardcoded list, because
    contract v1 §9 forbids writing another server's tool names down here.
    """
    bare = qualified_name.split(NAME_SEPARATOR)[-1] if NAME_SEPARATOR in qualified_name else qualified_name
    if is_write_tool(qualified_name):
        return "write"
    return "search" if "search" in bare or "retrieve" in bare else "records"


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    """Read the fenced prompt body out of the versioned markdown file.

    The rationale above the fence is for humans and must never reach the model,
    so the file is parsed rather than sent whole.
    """
    text = path.read_text()
    parts = text.split("\n---\n")
    if len(parts) < 2:
        raise ValueError(f"{path} has no '---' fence around the prompt body")
    return parts[-1].strip()


def is_write_tool(qualified_name: str) -> bool:
    _, _, tool_name = qualified_name.partition("__")
    bare_name = tool_name or qualified_name
    if bare_name.startswith("kb_retail_"):
        bare_name = bare_name[len("kb_retail_"):]
    return any(bare_name.startswith(v) or v in bare_name for v in WRITE_VERBS)


@dataclass
class TurnResult:
    answer: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    tools_offered: list[str] = field(default_factory=list)
    unreachable: dict[str, str] = field(default_factory=dict)
    rounds: int = 0
    pending_write: dict[str, Any] | None = None
    grounding_blocked: bool = False
    # Which halves of a composite answer were never retrieved, if any. Empty on
    # every non-composite question and on a complete composite answer.
    composite_incomplete: list[str] = field(default_factory=list)


def _strip_thinking(text: str) -> str:
    """Remove a reasoning model's <think> block, which is reasoning, not an answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# Hiragana, katakana, CJK ideographs and hangul.  A Qwen-family model trained
# heavily on Chinese occasionally answers an English question in Chinese; an
# agent reading that aloud to a caller has no answer at all, so it is caught
# here rather than being scored as a wrong answer.
_CJK_PATTERN = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def has_cjk(text: str) -> bool:
    return bool(_CJK_PATTERN.search(text or ""))


def _assistant_message(message: Any) -> dict[str, Any]:
    """One assistant reply, flattened to a plain replayable dict.

    The OpenAI SDK returns a Pydantic model, not a mapping, so `.get()` and a
    bare `messages.append(message)` both break against it.  Fields are copied by
    whitelist rather than dumped wholesale: vLLM adds provider-specific keys
    (`reasoning_content` among them) that are fine to read but are rejected when
    handed straight back as part of the next request's message list.
    """
    if hasattr(message, "model_dump"):
        dumped = message.model_dump(exclude_none=True)
    else:
        dumped = dict(message or {})

    flat: dict[str, Any] = {
        "role": "assistant",
        "content": dumped.get("content") or "",
    }
    calls = dumped.get("tool_calls") or []
    if calls:
        flat["tool_calls"] = [
            {
                "id": call.get("id") or "",
                "type": "function",
                "function": {
                    "name": call["function"]["name"],
                    "arguments": call["function"].get("arguments") or "{}",
                },
            }
            for call in calls
        ]
    return flat


def _tool_message(outcome: ToolOutcome, call_id: str) -> dict[str, str]:
    """What the model sees back from a tool it asked for.

    A failure is described in words rather than dropped, because the system
    prompt tells the model to answer from what it has and name what was missing.

    `tool_call_id` is mandatory on this role: the API rejects the whole request
    when a tool message does not link back to a call in the preceding assistant
    message, so a missing id fails the turn rather than degrading it.
    """
    if outcome.ok:
        body = json.dumps(outcome.payload, ensure_ascii=False)
    else:
        body = json.dumps({"unavailable": outcome.note or "tool call failed"})
    return {"role": "tool", "tool_call_id": call_id, "content": body}


def _client_result_message(outcome: ToolOutcome) -> dict[str, str]:
    """A search the *client* decided to run, handed back as supplied context.

    These results have no `tool_call_id` and can never have one — the model never
    requested them, so no assistant `tool_calls` entry exists to link to, and a
    `role: "tool"` message without that link is rejected outright.  Presenting
    them as user-supplied context is the honest shape: the content is identical,
    and the following instruction message already tells the model these are
    retrieved passages to cite.
    """
    if outcome.ok:
        body = json.dumps(outcome.payload, ensure_ascii=False)
    else:
        body = json.dumps({"unavailable": outcome.note or "tool call failed"})
    return {
        "role": "user",
        "content": f"Results retrieved for you from `{outcome.tool_name}`:\n{body}",
    }


_CLIENT: OpenAI | None = None
_BACKEND_STATUS: tuple[bool, str] | None = None


def chat_client() -> OpenAI:
    """The one OpenAI-protocol client, built lazily so importing costs nothing."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            base_url=CHAT_BASE_URL,
            api_key=CHAT_API_KEY,
            timeout=CHAT_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _CLIENT


def check_backend(model: str, force: bool = False) -> tuple[bool, str]:
    """Is the configured model actually being served right now?

    The platform document is explicit that these endpoints are not permanent and
    that a client should check `/v1/models` on startup and fail gracefully.  A
    missing model otherwise surfaces four rounds later as an opaque API error
    with a degraded banner that names the MCP servers — all of which are fine.

    Cached: this is a startup check, not a per-turn one.  A shared box with no
    per-user quota does not need an extra request on every question.
    """
    global _BACKEND_STATUS
    if _BACKEND_STATUS is not None and not force:
        return _BACKEND_STATUS
    try:
        served = {m.id for m in chat_client().models.list().data}
    except Exception as exc:  # noqa: BLE001 - any failure here is the same failure
        _BACKEND_STATUS = (False, f"{CHAT_BASE_URL} is unreachable ({exc}).")
        return _BACKEND_STATUS
    if model not in served:
        _BACKEND_STATUS = (
            False,
            f"'{model}' is not served by {CHAT_BASE_URL} "
            f"(available: {', '.join(sorted(served)) or 'none'}).",
        )
        return _BACKEND_STATUS
    _BACKEND_STATUS = (True, "")
    return _BACKEND_STATUS


async def _ask_model(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    allow_cjk: bool,
) -> dict[str, Any]:
    """One model call, normalised, with the language gate applied to prose.

    Temperature and a token ceiling are passed explicitly on every call.  They
    are not defaults worth inheriting: the API's own default of 1.0 is hotter
    than what this loop was measured on, and the difference lands on exactly the
    behaviours the eval set scores.
    """
    def _create(msgs: list[dict[str, Any]]):
        return chat_client().chat.completions.create(
            model=model,
            messages=msgs,
            tools=tools,
            temperature=CHAT_TEMPERATURE,
            max_tokens=CHAT_MAX_TOKENS,
        )

    reply = _assistant_message((await asyncio.to_thread(_create, messages)).choices[0].message)

    # Only prose is gated.  A tool call carrying CJK in an argument is a
    # retrieval query, not an answer the agent reads out.
    if allow_cjk or reply.get("tool_calls") or not has_cjk(reply["content"]):
        return reply

    retry_messages = messages + [
        {
            "role": "user",
            "content": (
                "Your previous reply was not in English. The agent reads this "
                "answer aloud to an English-speaking caller. Answer again in "
                "English only, using the same tool results."
            ),
        }
    ]
    candidate = _assistant_message(
        (await asyncio.to_thread(_create, retry_messages)).choices[0].message
    )
    return candidate if not has_cjk(candidate["content"]) else reply


def is_confirmed_by_user(question: str, history: Sequence[dict[str, Any]] | None) -> bool:
    q = question.strip().lower()
    confirm_words = ("yes", "confirm", "proceed", "go ahead", "approved", "execute", "sure", "ok", "okay")
    if any(q.startswith(w) or f" {w} " in f" {q} " or q == w for w in confirm_words):
        return True
    if history:
        for msg in reversed(history):
            if msg.get("role") == "assistant" and ("confirm" in msg.get("content", "").lower() or "would call" in msg.get("content", "").lower()):
                if any(w in q for w in confirm_words):
                    return True
    return False


async def _client_search(
    fleet: MCPFleet,
    result: TurnResult,
    query_text: str,
    round_index: int,
    reason: str,
    server: str | None = None,
) -> ToolOutcome | None:
    """Run a search the client decided on, and record it as a real tool result.

    Used where leaving the decision to the model was measured to fail. Returns
    None when no discovered tool on `server` advertises a text parameter, in
    which case the caller must not fabricate one.
    """
    tool = next(
        (
            t
            for t in fleet.tools
            if (server is None or t.server == server)
            and classify_tool_type(t.qualified_name) == "search"
            and search_query_argument(t.input_schema)
        ),
        None,
    )
    if tool is None:
        return None

    arg_name = search_query_argument(tool.input_schema)
    outcome = await fleet.call(tool.qualified_name, {arg_name: query_text})
    result.trace.append(
        {
            "round": round_index,
            "server": outcome.server,
            "tool": outcome.tool_name,
            "arguments": outcome.arguments,
            "ok": outcome.ok,
            "note": f"{outcome.note or ''} [client-issued: {reason}]".strip(),
            "payload": outcome.payload,
        }
    )
    return outcome


async def run_turn(
    question: str,
    history: list[dict[str, Any]] | None = None,
    model: str = DEFAULT_MODEL,
) -> TurnResult:
    """Answer one question, connecting to the fleet for the duration of the turn."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": load_system_prompt()}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": question})

    result = TurnResult(answer="")

    # Checked before the MCP fleet is dialled: with no model there is nothing to
    # reason with, so connecting to every server first would only add latency to
    # a turn that cannot succeed.
    backend_ok, backend_note = await asyncio.to_thread(check_backend, model)
    if not backend_ok:
        result.answer = (
            f"The chat model is not available, so I cannot answer. {backend_note}"
        )
        return result

    async with MCPFleet(load_server_configs()) as fleet:
        tools = fleet.tool_schemas()
        result.tools_offered = [t["function"]["name"] for t in tools]
        result.unreachable = dict(fleet.unreachable)

        if not tools:
            result.answer = (
                "No MCP server is reachable, so I have no sources to answer from. "
                "Start the retail server with "
                "`python3 server/main.py --transport http --port 8003`."
            )
            return result

        # Answered before the model runs. A greeting has nothing to retrieve, so
        # sending it round the loop only produces prose the grounding gate then
        # discards, leaving the user with a refusal to a question they never
        # asked. This reply makes no factual claim — it lists what was actually
        # discovered — so there is nothing here to be ungrounded about.
        if is_opener(question):
            result.answer = capability_summary(fleet.tools)
            return result

        nudged = False
        composite_nudged = False
        comparative_filled = False
        composite = is_composite_question(question)
        comparative = is_comparative_question(question)
        types_called: set[str] = set()
        servers_used: set[str] = set()
        for round_index in range(1, MAX_ROUNDS + 1):
            result.rounds = round_index
            message = await _ask_model(
                model, messages, tools, allow_cjk=has_cjk(question)
            )
            calls = message.get("tool_calls") or []

            if not calls:
                # An answer with no tool result behind it cannot be grounded, so
                # the client — not the prompt — decides what happens next.
                # Measured on qwen2.5:7b-instruct, 3 questions x 3 trials: the
                # model searched only 4 times out of 9 and answered the other 5
                # from parametric memory, complete with citations to real
                # document titles it had never retrieved.  A fabricated citation
                # is the single worst failure mode for a call-center assistant,
                # and no wording of the system prompt fixed it.
                if not result.trace:
                    if not nudged:
                        nudged = True
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You must call the appropriate MCP tool(s) (such as search, "
                                    "query_orders, query_customer, etc.) before answering. "
                                    "Do not output conversational plans or text preambles; "
                                    "invoke the tool calls directly now."
                                ),
                            }
                        )
                        continue
                    # Nudged once and still refusing to search: the model's prose
                    # is ungrounded by construction, so it is discarded rather
                    # than shown.
                    result.grounding_blocked = True
                    result.answer = (
                        "I don't know — I have no retrieved sources for this, and I "
                        "won't answer a policy question without them."
                    )
                    return result

                # A composite question answered from one half only is worse than
                # an incomplete answer: it reads as complete.  "Is that allowed"
                # answered from the record alone states a rule that was never
                # looked up; "did it happen" answered from the policy alone
                # asserts a fact about an order nobody queried.  Ask once for the
                # missing half, and say which half is missing rather than
                # repeating the question.
                # A comparative question answered from one server is not a
                # partial comparison, it is no comparison: measured on Q20, the
                # model searched retail only and presented retail's refund
                # timeline as the answer to "do refund timelines differ between
                # us and the bank?". The missing side is fetched rather than
                # requested, for the same reason as the composite half — a step
                # the model may skip is not a control.
                if (
                    comparative
                    and not comparative_filled
                    and round_index < MAX_ROUNDS
                    and result.trace
                ):
                    wanted = [
                        s
                        for s in servers_matching_question(question, fleet.tools, servers_used)
                        if s not in servers_used
                    ]
                    # Bounded at two so a vague question cannot fan out across
                    # every peer and blow the spurious-call budget.
                    if wanted:
                        comparative_filled = True
                        for peer in wanted[:2]:
                            outcome = await _client_search(
                                fleet, result, question, round_index,
                                f"comparative question missing {peer}", server=peer,
                            )
                            if outcome is None:
                                continue
                            servers_used.add(outcome.server)
                            types_called.add("search")
                            messages.append(_client_result_message(outcome))
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You now have results from more than one industry. "
                                    "Compare them explicitly: state each side's rule, "
                                    "say whether they differ, and cite each side to the "
                                    "server it came from."
                                ),
                            }
                        )
                        continue

                missing = {"search", "records"} - types_called
                if composite and missing == {"search"} and not composite_nudged and round_index < MAX_ROUNDS:
                    # Fetch the missing policy half directly rather than asking
                    # the model to do it.  Measured on Q17: asked once, the model
                    # answered anyway and cited "[retail: Returns and Refunds
                    # Policy]" — a document that does not exist in the corpus.
                    # Inventing a source is the worst failure a call-centre
                    # assistant has, and a request the model may decline is not a
                    # control.  The client knows the question and, from the
                    # record, the retailer, so it can retrieve the passages
                    # itself and hand them over as a real tool result.
                    composite_nudged = True
                    brand = brand_from_records(result.trace)
                    query_text = f"{brand} {question}".strip() if brand else question
                    outcome = await _client_search(
                        fleet, result, query_text, round_index,
                        "composite half missing",
                    )
                    if outcome is not None:
                        types_called.add("search")
                        servers_used.add(outcome.server)
                        messages.append(_client_result_message(outcome))
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Those are the policy passages for this question. "
                                    "Answer using both them and the record you already "
                                    "have, and cite only titles that appear in these "
                                    "results."
                                ),
                            }
                        )
                        continue

                if composite and missing and not composite_nudged and round_index < MAX_ROUNDS:
                    composite_nudged = True
                    needed = (
                        "search the policy documents"
                        if "search" in missing
                        else "look up the operational record"
                    )
                    have = "the operational record" if "search" in missing else "the policy"
                    # Name the retailer the record already proved.  These four
                    # retailers' windows range from 15 to 365 days, so a search
                    # without the brand does not return a vague answer, it
                    # returns a wrong one from the wrong company.
                    brand = brand_from_records(result.trace) if "search" in missing else ""
                    brand_hint = (
                        f" The record is a {brand} order, so search {brand}'s own "
                        f"policy and do not answer from another retailer's."
                        if brand else ""
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"This question needs both a policy rule and an "
                                f"operational record, and you only have {have}. "
                                f"Now {needed}, then answer using both.{brand_hint} "
                                f"Cite each half to the tool it came from."
                            ),
                        }
                    )
                    continue

                result.answer = _strip_thinking(message.get("content", "")) or (
                    "I don't know — the tools returned nothing I can answer from."
                )
                if composite and missing:
                    # Nudged and still one-sided.  The answer is shown, because
                    # half a grounded answer beats none, but it is marked so the
                    # UI and the scorecard can see it was incomplete rather than
                    # counting it as a clean composite answer.
                    result.composite_incomplete = sorted(missing)
                return result

            # Writes stop the loop and wait for a human yes (design doc §5), unless confirmed.
            for call in calls:
                name = call["function"]["name"]
                if is_write_tool(name):
                    args = call["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}

                    if not is_confirmed_by_user(question, history):
                        result.pending_write = {"tool": name, "arguments": args}
                        result.answer = (
                            f"This would call `{name}` with "
                            f"{json.dumps(args, ensure_ascii=False)}. "
                            "Please confirm before I execute this action."
                        )
                        return result
                    # Confirmed: allow loop to proceed to execute call below

            messages.append(message)

            # The call id is carried alongside name and arguments because every
            # result has to be linked back to the call that asked for it.
            prepared: list[tuple[str, str, dict[str, Any]]] = []
            for call in calls:
                args = call["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                prepared.append((call.get("id") or "", call["function"]["name"], args))

            outcomes = await asyncio.gather(
                *(fleet.call(name, args) for _, name, args in prepared)
            )
            for _, name, _args in prepared:
                types_called.add(classify_tool_type(name))
                if NAME_SEPARATOR in name:
                    servers_used.add(name.split(NAME_SEPARATOR)[0])

            for (call_id, _name, _args), outcome in zip(prepared, outcomes):
                result.trace.append(
                    {
                        "round": round_index,
                        "server": outcome.server,
                        "tool": outcome.tool_name,
                        "arguments": outcome.arguments,
                        "ok": outcome.ok,
                        "note": outcome.note,
                        "payload": outcome.payload,
                    }
                )
                messages.append(_tool_message(outcome, call_id))

    result.answer = (
        f"I stopped after {MAX_ROUNDS} rounds of tool calls without reaching an "
        "answer. Try a narrower question."
    )
    return result


def main() -> None:
    """Terminal entry point — the same loop the web UI drives, minus the UI."""
    import argparse

    parser = argparse.ArgumentParser(description="Ask the retail assistant one question.")
    parser.add_argument("question", nargs="+", help="the question to answer")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--trace", action="store_true", help="print every tool call")
    args = parser.parse_args()

    outcome = asyncio.run(run_turn(" ".join(args.question), model=args.model))

    if outcome.unreachable:
        for server, reason in outcome.unreachable.items():
            print(f"[degraded] {server}: {reason}")
    print(f"[prompt {PROMPT_VERSION}] [{outcome.rounds} round(s)] "
          f"[{len(outcome.tools_offered)} tool(s) discovered]\n")
    if args.trace:
        for event in outcome.trace:
            print(f"  -> {event['server']}.{event['tool']}({event['arguments']}) "
                  f"ok={event['ok']}")
            print(f"     {json.dumps(event['payload'], ensure_ascii=False)[:400]}\n")
    print(outcome.answer)


if __name__ == "__main__":
    main()
