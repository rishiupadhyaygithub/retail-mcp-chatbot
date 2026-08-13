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
that offline set. The one thing that does need the shared GB10 chat model is
step 6, and nothing above it depends on step 6.

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

### 6. Anything needing the shared GB10 chat model  *(NOT required for 1–5)*

Everything in this step talks to the team's shared Ollama box. Off that LAN, or
with `qwen3:8b` not yet pulled, these fail — and nothing above depends on them.

```bash
export OLLAMA_HOST=http://10.10.150.150:11434   # chat ONLY (qwen3:8b), pulled on GB10
python3 client/toolcall_test.py                 # exits 1 if the model is unreachable
# python3 client/main.py                        (to add)
```

Known state as of 13 Aug 2026: GB10 is unreachable from this machine and
`qwen3:8b` is not pulled, so `toolcall_test.py` exits 1 with
`model 'qwen3:8b' not found (status code: 404)`. Escalated per brief §13. The
§4 transcript in the design document is still the `qwen2.5:7b-instruct` proxy
run and gets replaced once GB10 is back.

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
