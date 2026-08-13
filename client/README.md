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
| `loop.py` | The tool-call loop: system prompt, five-round cap, grounding gate, write gate. |
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

## The grounding gate

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
