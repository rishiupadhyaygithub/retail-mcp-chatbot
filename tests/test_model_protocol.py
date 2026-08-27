#!/usr/bin/env python3
"""Tests for the chat-model wire protocol and the routing it depends on.

The loop moved from Ollama to vLLM's OpenAI-compatible API. That is not a config
change: the two protocols disagree about the shape of a reply object, about
whether a tool result must name the call it answers, and about the default
sampling temperature. Every one of those disagreements was a live failure here,
and none of them was covered by a test — the tool loop had no coverage at all,
which is why the `t.name` crash below survived in the routing path unnoticed.

Every case is a real defect that was found and fixed, and the docstring says
which. No chat model, no MCP server and no network: the API-shaped objects are
stubs, so this stays fast and runs offline.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for candidate in (REPO_ROOT, REPO_ROOT / "client", REPO_ROOT / "server"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import pytest  # noqa: E402

from client.loop import (  # noqa: E402
    CHAT_TEMPERATURE,
    _assistant_message,
    _client_result_message,
    _tool_message,
    check_backend,
    has_cjk,
)
from client.mcp_client import DiscoveredTool, MCPFleet, ToolOutcome  # noqa: E402


# --------------------------------------------------------------------------
# Stubs shaped like the objects the OpenAI SDK and the MCP session return.
# --------------------------------------------------------------------------


class _PydanticLike:
    """Stands in for `ChatCompletionMessage`, which is a model, not a mapping."""

    def __init__(self, dumped: dict) -> None:
        self._dumped = dumped

    def model_dump(self, exclude_none: bool = False) -> dict:
        if not exclude_none:
            return dict(self._dumped)
        return {k: v for k, v in self._dumped.items() if v is not None}


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _CallResult:
    def __init__(self, payload: dict, is_error: bool = False) -> None:
        self.content = [_TextBlock(json.dumps(payload))]
        self.is_error = is_error


class _StubSession:
    """One connected server, enough of it for `MCPFleet.call` to route."""

    def __init__(self, tools: list[DiscoveredTool], payload: dict) -> None:
        self.tools = tools
        self._payload = payload
        self.called_with: tuple[str, dict] | None = None

    async def call_tool(self, tool_name: str, arguments: dict) -> _CallResult:
        self.called_with = (tool_name, arguments)
        return _CallResult(self._payload)


def _retail_fleet() -> tuple[MCPFleet, _StubSession]:
    tools = [
        DiscoveredTool(
            server="retail",
            tool_name="kb_retail_search",
            description="search retail policy documents",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
    ]
    session = _StubSession(tools, {"results": [], "total_found": 0})
    fleet = MCPFleet(configs=[])
    fleet._sessions["retail"] = session  # type: ignore[assignment]
    return fleet, session


# --------------------------------------------------------------------------
# Tool results must link back to the call that asked for them.
# --------------------------------------------------------------------------


def test_tool_message_carries_the_call_id():
    """Ollama accepted `{role, content, name}`; the OpenAI API rejects it.

    A `role: "tool"` message that does not name a `tool_call_id` present in the
    preceding assistant message is a 400 on the whole request, not a degraded
    answer — so the loop failed on round two of every question that called a
    tool until the id was threaded through.
    """
    outcome = ToolOutcome(
        server="retail",
        tool_name="kb_retail_search",
        arguments={"query": "returns"},
        ok=True,
        payload={"results": [], "total_found": 0},
    )
    message = _tool_message(outcome, "call_abc123")

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_abc123"
    assert json.loads(message["content"])["total_found"] == 0


def test_tool_message_reports_failure_in_words():
    """A failed call is described, never dropped.

    The system prompt tells the model to answer from what it has and name what
    was missing, which it cannot do if the failure never reaches it.
    """
    outcome = ToolOutcome(
        server="retail",
        tool_name="kb_retail_query_orders",
        arguments={"order_id": "ORD-1"},
        ok=False,
        payload=None,
        note="retail server is unavailable (connection refused).",
    )
    message = _tool_message(outcome, "call_x")

    assert message["tool_call_id"] == "call_x"
    assert "unavailable" in json.loads(message["content"])


def test_client_issued_results_are_not_tool_messages():
    """The composite and comparative gates run searches the model never asked for.

    There is therefore no assistant `tool_calls` entry to link them to, and no
    id that could ever be minted for one — a synthesised id names a call that
    does not exist, which the API rejects exactly as it rejects a missing one.
    They are handed over as supplied context instead.
    """
    outcome = ToolOutcome(
        server="retail",
        tool_name="kb_retail_search",
        arguments={"query": "IKEA returns"},
        ok=True,
        payload={"results": [{"source": "IKEA US — Returns & Claims"}]},
    )
    message = _client_result_message(outcome)

    assert message["role"] == "user"
    assert "tool_call_id" not in message
    assert "kb_retail_search" in message["content"]
    assert "IKEA US — Returns & Claims" in message["content"]


# --------------------------------------------------------------------------
# The reply object is a model, not a dict.
# --------------------------------------------------------------------------


def test_assistant_message_flattens_a_pydantic_reply():
    """`response["message"]` and `message.get(...)` both break on the SDK's object.

    The old loop indexed the reply like a mapping, which is what Ollama returned.
    The OpenAI SDK returns a Pydantic model, so every access site had to move
    behind one normalisation step.
    """
    reply = _PydanticLike(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "retail__kb_retail_search",
                        "arguments": '{"query": "returns"}',
                    },
                }
            ],
        }
    )
    flat = _assistant_message(reply)

    assert flat["role"] == "assistant"
    assert flat["content"] == ""  # None is not a legal content value on replay
    assert flat["tool_calls"][0]["id"] == "call_1"
    assert flat["tool_calls"][0]["function"]["name"] == "retail__kb_retail_search"


def test_assistant_message_drops_provider_specific_fields():
    """vLLM adds keys the API will not accept back.

    `reasoning_content` is fine to read and is rejected when replayed as part of
    the next request's message list, so fields are copied by whitelist rather
    than dumped wholesale.
    """
    reply = _PydanticLike(
        {
            "role": "assistant",
            "content": "The window is 30 days.",
            "reasoning_content": "internal chain of thought",
            "refusal": None,
        }
    )
    flat = _assistant_message(reply)

    assert set(flat) == {"role", "content"}
    assert flat["content"] == "The window is 30 days."


def test_assistant_message_accepts_a_plain_mapping():
    """The normaliser must not itself depend on the SDK's object type."""
    flat = _assistant_message({"role": "assistant", "content": "hello"})
    assert flat == {"role": "assistant", "content": "hello"}


# --------------------------------------------------------------------------
# Sampling and language.
# --------------------------------------------------------------------------


def test_temperature_is_pinned_below_the_api_default():
    """Ollama defaulted to 0.8, the OpenAI API defaults to 1.0.

    Migrating without pinning this raises sampling temperature on exactly the
    axis the eval set scores — fabricated citations and language drift — while
    looking like a pure transport change.
    """
    assert CHAT_TEMPERATURE < 1.0


@pytest.mark.parametrize(
    "text, expected",
    [
        ("You have 30 days to return it.", False),
        ("退货期限为30天。", True),
        ("返品は30日以内です。", True),
        ("반품은 30일 이내입니다.", True),
        ("", False),
    ],
)
def test_cjk_detection(text, expected):
    """A Qwen-family model sometimes answers an English question in Chinese.

    An agent reading that aloud to a caller has no answer at all, so it is
    caught and retried rather than scored as a wrong answer.
    """
    assert has_cjk(text) is expected


# --------------------------------------------------------------------------
# Routing: the bare-name path.
# --------------------------------------------------------------------------


def test_bare_tool_name_routes_to_the_server_that_advertised_it():
    """`DiscoveredTool` has `tool_name`, not `name`.

    The fallback branch for an unqualified tool name read `t.name` and raised
    `AttributeError: 'DiscoveredTool' object has no attribute 'name'`. It went
    unnoticed because the previous model always emitted the qualified name; the
    system prompt names the bare tools, so a prompt-following model reaches this
    branch and took the whole turn down with it.
    """
    fleet, session = _retail_fleet()
    outcome = asyncio.run(fleet.call("kb_retail_search", {"query": "returns"}))

    assert outcome.ok
    assert outcome.server == "retail"
    assert outcome.tool_name == "kb_retail_search"
    assert session.called_with == ("kb_retail_search", {"query": "returns"})


def test_qualified_tool_name_still_routes():
    """The qualified path is the common one and must not regress."""
    fleet, session = _retail_fleet()
    outcome = asyncio.run(fleet.call("retail__kb_retail_search", {"query": "x"}))

    assert outcome.ok
    assert outcome.server == "retail"
    assert session.called_with == ("kb_retail_search", {"query": "x"})


def test_unknown_bare_tool_name_is_refused_not_crashed():
    """An unoffered name is a reportable outcome, not an exception."""
    fleet, _ = _retail_fleet()
    outcome = asyncio.run(fleet.call("kb_hotel_search", {"query": "x"}))

    assert not outcome.ok
    assert "not a tool this client offered" in outcome.note


# --------------------------------------------------------------------------
# Startup check.
# --------------------------------------------------------------------------


class _ModelList:
    def __init__(self, ids: list[str]) -> None:
        self.data = [type("M", (), {"id": i})() for i in ids]


class _StubChatClient:
    def __init__(self, ids: list[str] | None = None, error: Exception | None = None) -> None:
        self._ids = ids or []
        self._error = error
        outer = self

        class _Models:
            def list(self):
                if outer._error is not None:
                    raise outer._error
                return _ModelList(outer._ids)

        self.models = _Models()


def test_backend_check_accepts_a_served_model(monkeypatch):
    """The platform document says to check /v1/models on startup."""
    monkeypatch.setattr("client.loop.chat_client", lambda: _StubChatClient(["topaz-coder"]))
    ok, note = check_backend("topaz-coder", force=True)
    assert ok and note == ""


def test_backend_check_names_the_missing_model(monkeypatch):
    """The endpoint is explicitly not permanent, so this must fail readably.

    Without it, a re-provisioned box surfaces four rounds later as an opaque API
    error under a degradation banner that names the MCP servers, all of which
    are fine.
    """
    monkeypatch.setattr("client.loop.chat_client", lambda: _StubChatClient(["some-other-model"]))
    ok, note = check_backend("topaz-coder", force=True)
    assert not ok
    assert "topaz-coder" in note and "some-other-model" in note


def test_backend_check_fails_gracefully_when_unreachable(monkeypatch):
    """An unreachable gateway is reported, never raised into the turn."""
    monkeypatch.setattr(
        "client.loop.chat_client",
        lambda: _StubChatClient(error=ConnectionError("connection refused")),
    )
    ok, note = check_backend("topaz-coder", force=True)
    assert not ok
    assert "unreachable" in note
