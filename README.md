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
| `server/` | MCP server (no LLM) |
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

### 1. Prerequisites

```bash
# Python 3.11+.
# CHAT model runs on the shared GB10 Ollama server — the CLIENT points at it:
export OLLAMA_HOST=http://10.10.150.150:11434   # chat ONLY (qwen3:8b), pulled on GB10
# EMBEDDING runs LOCALLY on my host (10.10.180.132), NOT on GB10:
#   the MCP server embeds queries itself via sentence-transformers (bge-small-en-v1.5).
#   Nothing embedding-related touches GB10 (per manager, 2026-08-11).
pip install -r requirements.txt
```

### 2. Verify the tool-call loop (works today)

```bash
python3 client/toolcall_test.py
# Expect: TOOL CALL -> TOOL RESULT -> FINAL ANSWER -> PASS
```

### 3. Ingest the document corpus

```bash
# Build both chunking strategies (heading + packed):
python3 data/ingest.py --strategy heading --rebuild
python3 data/ingest.py --strategy packed --rebuild

# Dry-run stats only (no model load, no ChromaDB write):
python3 data/ingest.py --strategy packed --stats
```

### 4. Start the server  *(to add — Phase 1)*

```bash
# stdio transport:
# python3 server/main.py --transport stdio
# HTTP transport (interop day) — retail = port 8003, bind to LAN not localhost:
# python3 server/main.py --transport http --host 0.0.0.0 --port 8003
```

### 5. Start the client  *(to add)*

```bash
# python3 client/main.py
```

### 6. Run the eval harness

```bash
# Run against both strategies, scorecard to eval/scorecard_baseline.md:
python3 eval/harness.py

# Single strategy:
python3 eval/harness.py --strategy packed --top-k 5
```

## Models

- **Chat: `qwen3:8b`** via Ollama on the shared **GB10 server** (`10.10.150.150:11434`) — called only by the client. Team pick (~6–8 GB). Tool-calling verified on a Qwen-family instruct model as proxy (`qwen2.5:7b-instruct`); re-verified on `qwen3:8b` once pulled on GB10 — transcript in `docs/design_document.md` §4.
- **Embedding: `bge-small-en-v1.5`** via `sentence-transformers`, **local on my host** (`10.10.180.132`, ~130 MB) — called directly by the MCP server, never on GB10.

## Status

**Phase A (baseline gate) — DONE.** Corpus ingested (22 docs, 2 strategies), harness runs, baseline scorecard generated. Recall@5 = 100% (both strategies), Recall@1 = 90.9% heading / 81.8% packed. Phase B (MCP server) is next.
