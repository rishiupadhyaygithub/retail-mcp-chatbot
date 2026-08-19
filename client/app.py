#!/usr/bin/env python3
"""Serves the chat UI and the one API endpoint behind it.

Design document §6: one plain HTML/JS page served by the client, no framework
and no build step.  That is why this is `http.server` from the standard library
rather than FastAPI — the client's dependency list stays `ollama` + `mcp`, and a
colleague can run the UI straight from a clean checkout.

Binds to 127.0.0.1 on purpose.  The MCP *server* binds every interface because
teammates connect to it on interop day; this UI is for one person at one desk
and has no authentication, so it must not be reachable from the LAN.

    python3 client/app.py            # then open http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loop import DEFAULT_MODEL, MAX_ROUNDS, PROMPT_VERSION, run_turn  # noqa: E402

UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"

DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8080

MAX_QUESTION_BYTES = 4096


class Handler(BaseHTTPRequestHandler):
    model = DEFAULT_MODEL

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if self.path in ("/", "/index.html"):
            self._send(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/config":
            self._send_json(
                200,
                {
                    "model": self.model,
                    "prompt_version": PROMPT_VERSION,
                    "max_rounds": MAX_ROUNDS,
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return

        # Validate at the boundary: a bad length or an oversized body is a
        # client error, never an exception that takes the server down.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_QUESTION_BYTES:
            self._send_json(400, {"error": f"body must be 1..{MAX_QUESTION_BYTES} bytes"})
            return

        try:
            request = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "body is not JSON"})
            return

        question = str(request.get("question", "")).strip()
        history = request.get("history") or []
        if not question:
            self._send_json(400, {"error": "question is required"})
            return

        try:
            result = asyncio.run(run_turn(question, history=history, model=self.model))
        except Exception as exc:  # noqa: BLE001 - one bad turn must not kill the UI
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return

        self._send_json(
            200,
            {
                "answer": result.answer,
                "trace": result.trace,
                "tools_offered": result.tools_offered,
                "unreachable": result.unreachable,
                "rounds": result.rounds,
                "pending_write": result.pending_write,
                "grounding_blocked": result.grounding_blocked,
                # Which half of a composite answer was never retrieved. Returned
                # because an answer the client knows is one-sided must say so to
                # the person relying on it; a flag that stops at the server is
                # not a safeguard, it is a private note.
                "composite_incomplete": result.composite_incomplete,
                "model": self.model,
                "prompt_version": PROMPT_VERSION,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        # One tidy line per request instead of http.server's default noise.
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local chat UI.")
    parser.add_argument("--host", default=DEFAULT_UI_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    Handler.model = args.model
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"chat UI on http://{args.host}:{args.port}  (model: {args.model}, "
          f"prompt {PROMPT_VERSION})")
    print("MCP servers come from client/servers.json — start the retail server first.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
