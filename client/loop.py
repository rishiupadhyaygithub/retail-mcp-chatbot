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
from typing import Any

import ollama

from mcp_client import NAME_SEPARATOR, MCPFleet, ToolOutcome, load_server_configs

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt_v2.md"
PROMPT_VERSION = "v2"

# Design doc §5.  Five is enough for a cross-server comparison (one search per
# server plus a synthesis round) and short enough that a loop costs seconds.
MAX_ROUNDS = 5

# `qwen3:1.7b` is the fastest model that fits this 8 GB machine, but it emitted
# a tool call in 0 of 3 trials on a plain policy question — it answers from
# memory instead — so it cannot drive this loop at all.  `qwen2.5:7b-instruct`
# is the largest model that still fits entirely on the GPU here and is the same
# proxy the design document's §4 tool-calling transcript used.  The demo model
# stays `qwen3:8b` on GB10; override with CHAT_MODEL.
DEFAULT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:7b-instruct")

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
    """Remove qwen3's <think> block, which is reasoning, not an answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _tool_message(outcome: ToolOutcome) -> dict[str, str]:
    """What the model sees back from a tool.

    A failure is described in words rather than dropped, because the system
    prompt tells the model to answer from what it has and name what was missing.
    """
    if outcome.ok:
        body = json.dumps(outcome.payload, ensure_ascii=False)
    else:
        body = json.dumps({"unavailable": outcome.note or "tool call failed"})
    return {"role": "tool", "content": body, "name": outcome.tool_name}


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

    async with MCPFleet(load_server_configs()) as fleet:
        tools = fleet.ollama_tools()
        result.tools_offered = [t["function"]["name"] for t in tools]
        result.unreachable = dict(fleet.unreachable)

        if not tools:
            result.answer = (
                "No MCP server is reachable, so I have no sources to answer from. "
                "Start the retail server with "
                "`python3 server/main.py --transport http --port 8003`."
            )
            return result

        nudged = False
        composite_nudged = False
        composite = is_composite_question(question)
        types_called: set[str] = set()
        for round_index in range(1, MAX_ROUNDS + 1):
            result.rounds = round_index
            response = await asyncio.to_thread(
                ollama.chat, model=model, messages=messages, tools=tools
            )
            message = response["message"]
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
                                    "You have not searched yet. Call a search tool "
                                    "before answering. If no tool can answer this, "
                                    "reply with exactly: I don't know."
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
                    search_tool = next(
                        (t for t in fleet.tools
                         if classify_tool_type(t.qualified_name) == "search"
                         and search_query_argument(t.input_schema)),
                        None,
                    )
                    if search_tool is not None:
                        arg_name = search_query_argument(search_tool.input_schema)
                        query_text = f"{brand} {question}".strip() if brand else question
                        outcome = await fleet.call(
                            search_tool.qualified_name, {arg_name: query_text}
                        )
                        types_called.add("search")
                        result.trace.append(
                            {
                                "round": round_index,
                                "server": outcome.server,
                                "tool": outcome.tool_name,
                                "arguments": outcome.arguments,
                                "ok": outcome.ok,
                                "note": (outcome.note or "") + " [client-issued: composite half missing]",
                                "payload": outcome.payload,
                            }
                        )
                        messages.append(_tool_message(outcome))
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

            prepared: list[tuple[str, dict[str, Any]]] = []
            for call in calls:
                args = call["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                prepared.append((call["function"]["name"], args))

            outcomes = await asyncio.gather(
                *(fleet.call(name, args) for name, args in prepared)
            )
            for name, _ in prepared:
                types_called.add(classify_tool_type(name))

            for outcome in outcomes:
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
                messages.append(_tool_message(outcome))

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
