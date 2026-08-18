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

from mcp_client import MCPFleet, ToolOutcome, load_server_configs

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt_v1.md"
PROMPT_VERSION = "v1"

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

                result.answer = _strip_thinking(message.get("content", "")) or (
                    "I don't know — the tools returned nothing I can answer from."
                )
                return result

            # Writes stop the loop and wait for a human yes (design doc §5).
            for call in calls:
                name = call["function"]["name"]
                if is_write_tool(name):
                    args = call["function"]["arguments"]
                    if isinstance(args, str):
                        args = json.loads(args)
                    result.pending_write = {"tool": name, "arguments": args}
                    result.answer = (
                        f"This would call `{name}` with "
                        f"{json.dumps(args, ensure_ascii=False)}. "
                        "Confirm before I run it."
                    )
                    return result

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
