#!/usr/bin/env python3
"""Fleet of MCP client sessions, one per intern's server.

Two rules from the contract shape this whole file:

* **Runtime discovery only** (contract v1 §9).  No tool name, argument or
  schema is written down here.  Whatever a server advertises in `tools/list` is
  what the chat model is offered, so a teammate can rename a tool the night
  before interop day and this client picks it up on the next turn.
* **A dead or slow server must not kill the client.**  Every connect and every
  call is bounded by a timeout, and a failure becomes a note the model can read
  rather than an exception.  "One server down", "all down" and "restarting
  mid-session" are all the same code path.

**Why each session gets its own task.**  The MCP SDK builds on anyio, and an
anyio cancel scope must be exited by the same task that entered it.  Connecting
several servers with `asyncio.gather` (or wrapping a connect in
`asyncio.wait_for`) enters the session's scope inside a temporary child task and
exits it from the parent, which fails at shutdown with
`RuntimeError: Attempted to exit cancel scope in a different task than it was
entered in` — after the answer is already correct, so it looks like a shutdown
bug rather than a design error.  Instead each server runs a long-lived owner
task that connects, serves tool calls off a queue, and closes its own session.
Timeouts are applied by the *caller* waiting on a future, so no scope ever
crosses a task boundary.

Sessions live for one conversation turn rather than the life of the process.  A
held-open Streamable HTTP session goes stale when the far end restarts and the
failure surfaces on some later unrelated turn; reconnecting costs milliseconds
on a LAN and makes "server restarted" indistinguishable from "server was fine".
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CONFIG_PATH = Path(__file__).resolve().parent / "servers.json"

# Ollama tool names must be a single identifier, so the server name is folded in
# with a separator that cannot appear in an MCP tool name.
NAME_SEPARATOR = "__"


@dataclass
class ServerConfig:
    name: str
    url: str
    timeout_seconds: float = 15.0
    enabled: bool = True


@dataclass
class DiscoveredTool:
    """One tool as advertised by one server, plus the routing info to call it."""

    server: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return f"{self.server}{NAME_SEPARATOR}{self.tool_name}"


@dataclass
class ToolOutcome:
    """What actually happened on one tool call — success or failure, uniformly."""

    server: str
    tool_name: str
    arguments: dict[str, Any]
    ok: bool
    payload: Any
    note: str = ""


def load_server_configs(path: Path = CONFIG_PATH) -> list[ServerConfig]:
    raw = json.loads(path.read_text())
    return [
        ServerConfig(
            name=entry["name"],
            url=entry["url"],
            timeout_seconds=float(entry.get("timeout_seconds", 15)),
            enabled=bool(entry.get("enabled", True)),
        )
        for entry in raw["servers"]
    ]


def describe_exception(exc: BaseException) -> str:
    """A one-line cause an operator can act on.

    The MCP transport runs inside an anyio task group, so a refused connection
    surfaces as an `ExceptionGroup` whose own message is only
    `unhandled errors in a TaskGroup (1 sub-exception)` — it names no host, no
    port and no reason, which is useless in the degradation banner.  The real
    cause is nested inside, sometimes several groups deep, so unwrap to the
    leaves and report those.

    Duck-typed on `.exceptions` rather than `except*` or an `ExceptionGroup`
    import, because the builtin only exists on 3.11+ and this runs on 3.10,
    where anyio raises the `exceptiongroup` backport instead.
    """
    leaves: list[str] = []
    seen: set[int] = set()

    def walk(err: BaseException) -> None:
        if id(err) in seen:  # defensive: a cycle would otherwise hang the client
            return
        seen.add(id(err))
        nested = getattr(err, "exceptions", None)
        if nested:
            for sub in nested:
                walk(sub)
            return
        text = str(err).strip()
        # Bare OSError subclasses often stringify to nothing useful on their own.
        if not text and err.__cause__ is not None:
            text = str(err.__cause__).strip()
        leaves.append(f"{type(err).__name__}: {text}" if text else type(err).__name__)

    walk(exc)
    # Distinct causes only, order preserved — three identical refusals from one
    # retrying transport should read as one reason, not three.
    unique = list(dict.fromkeys(leaves))
    return "; ".join(unique) if unique else f"{type(exc).__name__}: {exc}"


class _ServerSession:
    """One server, owned end to end by one asyncio task.

    Everything that touches the MCP session — connect, discover, call, close —
    runs inside `_owner`.  The rest of the client only ever puts requests on a
    queue and waits on futures, which is what keeps anyio's cancel scopes intact.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.tools: list[DiscoveredTool] = []
        self.error: str = ""
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ready: asyncio.Future = asyncio.get_event_loop().create_future()
        self._task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Connect and discover.  Returns False (never raises) on any failure."""
        self._task = asyncio.ensure_future(self._owner())
        try:
            # shield: a connect that overruns its budget must not cancel the
            # owner task mid-handshake — `stop()` unwinds it cleanly instead.
            await asyncio.wait_for(
                asyncio.shield(self._ready), self.config.timeout_seconds
            )
        except asyncio.TimeoutError:
            self.error = f"no response within {self.config.timeout_seconds:.0f}s"
            return False
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            self.error = describe_exception(exc)
            return False
        return True

    async def _owner(self) -> None:
        try:
            async with streamable_http_client(self.config.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = [
                        DiscoveredTool(
                            server=self.config.name,
                            tool_name=tool.name,
                            description=tool.description or "",
                            input_schema=tool.input_schema
                            or {"type": "object", "properties": {}},
                        )
                        for tool in listed.tools
                    ]
                    if not self._ready.done():
                        self._ready.set_result(None)
                    await self._serve(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._ready.done():
                self._ready.set_exception(exc)
            self.error = describe_exception(exc)
            self._fail_pending(exc)

    async def _serve(self, session: ClientSession) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            tool_name, arguments, future = item
            try:
                result = await session.call_tool(tool_name, arguments)
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

    def _fail_pending(self, exc: BaseException) -> None:
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is None:
                continue
            _, _, future = item
            if not future.done():
                future.set_exception(exc)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]):
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        await self._queue.put((tool_name, arguments, future))
        # shield for the same reason as in start(): a caller-side timeout must
        # not cancel the owner task while it is mid-request.
        return await asyncio.wait_for(
            asyncio.shield(future), self.config.timeout_seconds
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        try:
            await asyncio.wait_for(asyncio.shield(self._task), 5)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001 - shutdown is best effort
                pass


@dataclass
class MCPFleet:
    """Connects to every enabled server, then routes the model's tool calls.

    Use as an async context manager.  Servers that fail to connect appear in
    `unreachable` and contribute no tools; the fleet still works.
    """

    configs: list[ServerConfig]
    unreachable: dict[str, str] = field(default_factory=dict)
    _sessions: dict[str, _ServerSession] = field(default_factory=dict)

    async def __aenter__(self) -> "MCPFleet":
        enabled = [c for c in self.configs if c.enabled]
        candidates = [(c, _ServerSession(c)) for c in enabled]
        # Connect in parallel: one slow server must not serialise the others.
        # Safe to gather because `start` only awaits a future — the session's
        # own cancel scope stays inside its owner task.
        results = await asyncio.gather(*(s.start() for _, s in candidates))
        for (config, session), ok in zip(candidates, results):
            if ok:
                self._sessions[config.name] = session
            else:
                self.unreachable[config.name] = session.error or "unreachable"
                await session.stop()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        for session in self._sessions.values():
            await session.stop()
        self._sessions.clear()

    @property
    def tools(self) -> list[DiscoveredTool]:
        return [tool for session in self._sessions.values() for tool in session.tools]

    def ollama_tools(self) -> list[dict[str, Any]]:
        """Every discovered tool, in the shape Ollama's chat API expects.

        The server name is prefixed onto the description as well as the tool
        name so the model can honour the system prompt's "pick the tool whose
        description matches the industry" rule without the client hardcoding a
        mapping of industries to servers.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.qualified_name,
                    "description": f"[{tool.server} server] {tool.description}".strip(),
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.tools
        ]

    async def call(self, qualified_name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Route one model-requested tool call to the server that advertised it."""
        if NAME_SEPARATOR in qualified_name:
            server, _, tool_name = qualified_name.partition(NAME_SEPARATOR)
        else:
            tool_name = qualified_name
            matching = [s for s, session in self._sessions.items() if any(t.name == tool_name for t in session.tools)]
            if matching:
                server = matching[0]
            else:
                return ToolOutcome(
                    server="?",
                    tool_name=qualified_name,
                    arguments=arguments,
                    ok=False,
                    payload=None,
                    note=f"'{qualified_name}' is not a tool this client offered.",
                )

        session = self._sessions.get(server)
        if session is None:
            reason = self.unreachable.get(server, "not connected")
            return ToolOutcome(
                server=server,
                tool_name=tool_name,
                arguments=arguments,
                ok=False,
                payload=None,
                note=f"{server} server is unavailable ({reason}).",
            )

        try:
            result = await session.call_tool(tool_name, arguments)
        except asyncio.TimeoutError:
            return ToolOutcome(
                server=server,
                tool_name=tool_name,
                arguments=arguments,
                ok=False,
                payload=None,
                note=f"{server} server did not respond within "
                f"{session.config.timeout_seconds:.0f}s.",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolOutcome(
                server=server,
                tool_name=tool_name,
                arguments=arguments,
                ok=False,
                payload=None,
                note=f"{server} server failed: {type(exc).__name__}: {exc}",
            )

        text = "".join(
            block.text for block in result.content if getattr(block, "type", "") == "text"
        )
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError:
            payload = text

        # A contract application error ({error, message, retryable}) is a
        # successful protocol exchange carrying a refusal, and `is_error` marks
        # a framework-level tool error.  Both mean "tell the model", not "the
        # client is broken".
        failed = bool(result.is_error) or (
            isinstance(payload, dict) and "error" in payload and "results" not in payload
        )
        note = ""
        if failed and isinstance(payload, dict):
            note = str(payload.get("message", payload.get("error", "")))
        return ToolOutcome(
            server=server,
            tool_name=tool_name,
            arguments=arguments,
            ok=not failed,
            payload=payload,
            note=note,
        )
