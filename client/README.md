# client/

The chatbot host. **All reasoning lives here** — the MCP servers do retrieval
and data and never call a chat LLM.

```bash
pip install -r client/requirements.txt

# 1. Start the retail MCP server (any terminal):
python3 server/main.py --transport http --host 127.0.0.1 --port 8003

# 2a. Web UI — open http://127.0.0.1:8080
python3 client/app.py

# 2b. Or the same loop from the terminal:
python3 client/loop.py --trace "Can a customer return opened electronics?"
```

| File | What it is |
|---|---|
| `app.py` | Serves the UI and `POST /api/chat`. Binds `127.0.0.1` — no auth, never expose it. |
| `loop.py` | The tool-call loop: system prompt, five-round cap, and the five gates below. |
| `composite.py` | Deterministic dual-provenance synthesis for the record+policy questions. |
| `workflow.py` | Multi-turn state machine: clarification, confirmation, action states. |
| `mcp_client.py` | One MCP session per server. Runtime tool discovery, timeouts, degradation. |
| `servers.json` | Server addresses only. **No tool names** — contract v1 §9 requires discovery. |
| `ui/index.html` | The page. Plain HTML/JS, no framework, no build step (design doc §6). |
| `toolcall_test.py` | Original smoke test proving a local model can emit a tool call at all. |

## Chat model

`CHAT_MODEL` picks the model, `OLLAMA_HOST` picks the box.

```bash
OLLAMA_HOST=http://10.10.150.150:11434 CHAT_MODEL=qwen3:8b python3 client/app.py   # demo, GB10
OLLAMA_HOST=http://localhost:11434 python3 client/app.py                            # local default
```

The local default is `qwen2.5:7b-instruct`, not the faster `qwen3:1.7b`.
Measured here: **`qwen3:1.7b` emitted a tool call in 0 of 3 trials** on a plain
policy question — it answers from memory instead — so it cannot drive this loop
regardless of how fast it is. `qwen2.5:7b-instruct` is the largest model that
still fits entirely on this 8 GB machine's GPU.

## The gates

Five client-side gates sit in `loop.py`. Each exists because a specific failure
was **measured**, and each was tried as prompt wording first and moved into code
only when wording did not hold. This is the most important lesson from building
the client: **the prompt states intent, code provides the guarantee.**

| Gate | Failure it fixes | What it does |
|---|---|---|
| Grounding | Answered from memory, citing real documents it never retrieved | Nudges once, then discards the ungrounded prose |
| Write confirmation | A write could execute unattended | Stops and waits for a human yes |
| Composite completeness | Answered "is that allowed *and* did it happen" from one half, presented as complete | Fetches the missing half itself |
| Brand scoping | Returned IKEA's 365-day window for an Amazon order | Names the retailer the record proved |
| Comparative completeness | Answered "do we differ from the bank?" from retail alone | Fetches the other side itself |

The last three **fetch** the evidence rather than asking the model for it. That
distinction is deliberate: Q17 was asked once to search before answering and
answered anyway, citing `[retail: Returns and Refunds Policy]` — a document that
does not exist in the corpus. A step the model may skip is not a control.

What the gates decide is surfaced rather than kept server-side:
`composite_incomplete` and `grounding_blocked` are returned by `/api/chat` and
rendered as banners, because an answer the client knows is one-sided has to say
so where the answer is actually read.

## The grounding gate in detail

The system prompt alone does not produce grounded answers. Measured on
`qwen2.5:7b-instruct`, 3 questions x 3 trials, before the gate existed:

| | searched | answered from memory |
|---|---|---|
| answerable questions | 4/6 | 2/6 — **with citations to real documents it never retrieved** |

A fabricated citation is the worst failure this assistant can produce, so the
decision was moved out of the prompt and into `loop.py`: if the model tries to
answer with no tool result behind it, the client nudges it once to search, and
if it still refuses, the model's prose is **discarded** and replaced with a
refusal. After the gate, answerable questions searched 6/6, and an
unanswerable one is refused whether or not the model bothers to search.

Citation *formatting* is still inconsistent — the model sometimes writes
"Target states…" instead of `[retail: Target — Returns]`. That is a scorecard
row, not a crash, and it is measured rather than assumed.
