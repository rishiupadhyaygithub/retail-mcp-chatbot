# Retail MCP Server + Chatbot Client

Internship project: an **MCP server** for the **Retail** domain, plus a **chatbot client** that connects to all four interns' servers.

> **Core rule:** the server does retrieval + data + actions and **never calls a chat LLM**. The client does all reasoning, tool selection, and text generation.
>
> **Embedding is retrieval, not generation:** the MCP server runs a **local** embedding model on my host (`bge-small-en-v1.5`, off GB10) to turn a query into a vector. The server calls the embedder **directly** — never through the client, and there is **no contact between the chat model and the MCP server** (per manager, 2026-08-11).

## Repo layout

| Path | Contents |
|------|----------|
| `docs/` | design document, addendum, retro |
| `eval/` | eval set, harness, scorecards |
| `conformance/` | reports on the other three interns' servers |
| `server/` | MCP server (no LLM) — protocol adapter plus the frozen `retrieval.py` |
| `client/` | host, client sessions, UI |
| `data/` | corpus sources list, ingestion scripts, dataset generator |
| `prompts/` | system prompt, versioned |
| `contract/` | shared, jointly owned across all 4 interns |

## Phases

1. **Documents (RAG)** — answer from retail policy docs, with citations.
2. **Records** — structured queries over catalog / inventory / orders (SQLite).
3. **Actions** — writes (returns, cancellations) with a confirmation step.

---

## Run it from a clean checkout

> A colleague should be able to clone and run everything from this section alone. *(Commands marked `(to add)` land as each phase is built.)*

**Steps 1–5 run entirely on your own machine, offline.** No GB10, no Ollama, no
other intern's server, no network at all after `pip install`. Everything graded
at the baseline gate — corpus, retrieval, MCP server, tests, scorecard — is in
that offline set. **Step 6 is the chat UI**: it needs a chat model, but Ollama
on this machine is enough. Only step 7 needs the shared GB10 box, and nothing
above it depends on step 7.

Verified by cloning this repo to an empty directory and running steps 1–5 in
order: ingest exits 0 for both strategies, 11 tests pass, and the harness
reproduces Recall@5 = 100%.

### 1. Prerequisites

```bash
# Python 3.10+ (developed and verified on 3.10.0).
pip install -r requirements.txt
```

First run downloads the `bge-small-en-v1.5` weights (~130 MB) into the local
Hugging Face cache. Every run after that is offline — the server opens the model
with `local_files_only=True` and Chroma telemetry is disabled, so a started
server makes no outbound request.

### 2. Ingest the document corpus

```bash
# Build both chunking strategies (heading + packed):
python3 data/ingest.py --strategy heading --rebuild
python3 data/ingest.py --strategy packed --rebuild

# Dry-run stats only (no model load, no ChromaDB write):
python3 data/ingest.py --strategy packed --stats
```

### 3. Run the tests

```bash
python3 -m pytest tests/ -q
# Expect: 11 passed. Covers the contract payloads, the malformed-argument
# errors, and a live Streamable HTTP server on a real socket.
```

### 4. Start the server

```bash
# stdio transport:
python3 server/main.py --transport stdio
# HTTP transport (interop day) — retail = port 8003, bind to LAN not localhost:
python3 server/main.py --transport http --host 0.0.0.0 --port 8003
```

`--transport http` is contract v1 §7's network transport and serves **MCP
Streamable HTTP** at **`/mcp`** — interop clients connect to
`http://10.10.180.132:8003/mcp`. `--transport sse` selects the pre-2025-03-26
SSE transport (`/sse`, `/messages/`), which MCP has deprecated; it is kept only
for a client that has not migrated. See `server/README.md` for the contract
surface and `server/conformance_matrix.md` for requirement-to-test traceability.

### 5. Run the eval harness

```bash
# Run against both strategies, scorecard to eval/scorecard_baseline.md:
python3 eval/harness.py

# Single strategy:
python3 eval/harness.py --strategy packed --top-k 5
```

### 6. Talk to it — the chat UI on localhost

Steps 1–5 prove the retrieval half but there is nothing to look at. This is the
part a human uses. It needs a chat model; Ollama on **this** machine is enough,
GB10 is not required.

```bash
pip install -r client/requirements.txt
ollama pull qwen2.5:7b-instruct

# terminal 1 — the MCP server
python3 server/main.py --transport http --host 127.0.0.1 --port 8003

# terminal 2 — the client + UI, then open http://127.0.0.1:8080
python3 client/app.py
```

Type a question, get an answer with the passages it came from and every tool
call one click away. Same loop without the browser:

```bash
python3 client/loop.py --trace "Can a customer return opened electronics?"
```

The UI binds `127.0.0.1` deliberately: the *server* binds every interface for
interop day, but the UI has no authentication and is for one person at one desk.

See `client/README.md` for the model choice (`qwen3:1.7b` cannot tool-call at
all — 0 of 3 trials) and for the grounding gate that stops the model answering
from memory with invented citations.

### 7. Anything needing the shared GB10 chat model  *(NOT required for 1–6)*

Everything in this step talks to the team's shared Ollama box. Off that LAN, or
with `qwen3:8b` not yet pulled, these fail — and nothing above depends on them.

```bash
export OLLAMA_HOST=http://10.10.150.150:11434   # chat ONLY (qwen3:8b), pulled on GB10
python3 client/toolcall_test.py                 # exits 1 if the model is unreachable
# python3 client/main.py                        (to add)
```

Known state as of 13 Aug 2026: GB10 is unreachable from this machine. Escalated
per brief §13. The §4 transcript in the design document is still the
`qwen2.5:7b-instruct` proxy run and gets replaced once GB10 is back.

**Local fallback while GB10 is down.** Ollama runs on this host too, so the
tool-call loop stays testable — point `OLLAMA_HOST` at `http://localhost:11434`.
But this is an 8 GB M2, and model choice matters. Measured here, same prompt,
warm figure excludes model load:

| Model | Fits GPU | Total | Load | Warm | Verdict |
|---|---|---|---|---|---|
| `qwen3:1.7b` | 100% GPU, 1.5 GB | 5.1 s | 3.5 s | **~1.6 s** | use this locally |
| `qwen2.5:7b-instruct` | 100% GPU, 4.6 GB | 19.0 s | 15.6 s | ~3.4 s | workable, tight |
| `qwen3:8b` | **20% CPU / 80% GPU** | **57.7 s** | 9.1 s | ~48 s | unusable on 8 GB |

`qwen3:8b` is the team's chosen chat model and it is pulled here, but it does
not fit in this machine's unified memory and spills to CPU, so a nine-token
reply takes ~58 s against a brief target of p50 ≤ 4 s end-to-end. That is
exactly what the shared GB10 box is for. Develop against `qwen3:1.7b` locally,
demo against `qwen3:8b` on GB10.

Load only one model at a time — three resident at once exhausts 8 GB and Ollama
starts returning empty responses. `ollama stop <model>` between runs.

**Embedding never touches GB10.** The MCP server embeds queries itself with
`sentence-transformers` (`bge-small-en-v1.5`) on this host, per the manager's
2026-08-11 decision.

## Models

- **Chat: `qwen3:8b`** via Ollama on the shared **GB10 server** (`10.10.150.150:11434`) — called only by the client. Team pick (~6–8 GB). Tool-calling verified on a Qwen-family instruct model as proxy (`qwen2.5:7b-instruct`); re-verified on `qwen3:8b` once pulled on GB10 — transcript in `docs/design_document.md` §4.
- **Embedding: `bge-small-en-v1.5`** via `sentence-transformers`, **local on my host** (`10.10.180.132`, ~130 MB) — called directly by the MCP server, never on GB10.

## Status

**Phase A (baseline gate) — DONE.** Corpus ingested (22 docs, 2 strategies), harness runs, baseline scorecard generated. Recall@5 = 100% (both strategies), Recall@1 = 90.9% heading / 81.8% packed.

**Phase B (MCP server) — IMPLEMENTED / local verification complete.**
`kb_retail_search`, `kb_retail_documents`, and `kb_retail_search_template` are
available over stdio and over MCP Streamable HTTP at `/mcp` (contract v1 §7's
`http`). The server uses the frozen heading collection and local embeddings
only; it never calls GB10 or an LLM. Cross-machine interop and an unmodified
third-party-client check remain the final acceptance steps.

**Phase C (client + UI) — first vertical slice running.** `client/` discovers
tools at runtime from `client/servers.json`, runs the five-round tool-call loop
against a local Ollama model, and serves a plain HTML/JS page on
`127.0.0.1:8080`. Verified end to end against the live retail server: question
in, `kb_retail_search` called, five passages returned, answer rendered with its
sources and raw tool payloads. The other three servers stay `"enabled": false`
in the config until interop day and their absence does not affect a turn.
Still to come: the routing/answer-quality scorecard rows, which need this
client plus the eval set, and the conformance reports, which need teammates.
