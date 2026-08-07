# Retail MCP Server + Chatbot Client

Internship project: build an **MCP (Model Context Protocol) server** for the **Retail** domain, plus a **chatbot client** that connects to all four interns' servers.

## Core architecture rule

> **The server is dumb. The client is smart.**
> Server = retrieval + data + actions, and **never calls an LLM**.
> Client = all reasoning, tool selection, and text generation.

## Phases

1. **Documents (RAG)** — answer questions from retail policy/manual docs, with citations.
2. **Records** — structured queries over catalog / inventory / orders (SQLite).
3. **Actions** — state-changing writes (returns, cancellations) with a confirmation step.

## Repo contents

| File | What it is |
|------|------------|
| [`design_doc.md`](design_doc.md) | Design document (deliverable #1) |
| [`contract_v1.md`](contract_v1.md) | Interop contract shared across all 4 servers (deliverable #2) |
| [`eval_set.md`](eval_set.md) | 28-question evaluation set + scoring plan (deliverable #3) |
| [`toolcall_test.py`](toolcall_test.py) | Smoke test proving the local model drives the tool-call loop |

## Chat model

`qwen2.5:7b-instruct` via [Ollama](https://ollama.com), running locally. Verified reliable at tool-calling.

## Run the tool-call smoke test

```bash
pip install ollama
ollama pull qwen2.5:7b-instruct
python3 toolcall_test.py
```

## Status

Pre-build. Design doc, contract, and eval set drafted; Phase 1 build next.
