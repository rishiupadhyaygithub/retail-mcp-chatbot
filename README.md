# Retail MCP Server + Chatbot Client

Internship project: an **MCP server** for the **Retail** domain, plus a **chatbot client** that connects to all four interns' servers.

> **Core rule:** the server does retrieval + data + actions and **never calls an LLM**. The client does all reasoning, tool selection, and text generation.

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
# Python 3.11+ and Ollama (https://ollama.com)
brew install ollama          # macOS
ollama serve                 # start the model server (or: brew services start ollama)
ollama pull qwen2.5:7b-instruct
pip install ollama
```

### 2. Verify the tool-call loop (works today)

```bash
python3 client/toolcall_test.py
# Expect: TOOL CALL -> TOOL RESULT -> FINAL ANSWER -> PASS
```

### 3. Ingest the document corpus  *(to add — Phase 1)*

```bash
# python3 data/ingest.py
```

### 4. Start the server  *(to add — Phase 1)*

```bash
# stdio transport:
# python3 server/main.py --transport stdio
# HTTP transport (interop day):
# python3 server/main.py --transport http --port 8001
```

### 5. Start the client  *(to add)*

```bash
# python3 client/main.py
```

### 6. Run the eval harness  *(to add)*

```bash
# python3 eval/run_evals.py
```

## Chat model

`qwen2.5:7b-instruct` via Ollama, local. Verified reliable at tool-calling — transcript in `docs/design_document.md` §7.

## Status

Pre-build. Design doc, contract, and eval set drafted. Phase 1 (RAG server) is next.
