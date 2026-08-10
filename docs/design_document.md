# Retail MCP Server + Chatbot Client — Design Document v1

**Author:** (your name) — Intern, Retail
**Date:** 2026-08-07
**Status:** Draft for review / Contract v1 input
**Deadline:** Wed 2026-08-12

> Everything in *(italics/parens)* is a placeholder or a decision you should confirm. Read top to bottom, correct anything wrong, delete these notes before you submit.

---

## 1. Overview & Goal

We are building two things:

1. **A Retail MCP server** — exposes retail data and actions as MCP *tools*, *resources*, and *prompts*. It does **retrieval and data access only**. It never calls an LLM.
2. **A chatbot client** — connects to all four interns' MCP servers (Retail, plus the other three industries), does all the reasoning/generation with an LLM, decides which tools to call, and answers the user.

The hard architectural rule for the whole project:

> **The server is dumb. The client is smart.**
> Server = retrieval + data + actions. Client = all reasoning, planning, and text generation.
> The server MUST NOT call any LLM. If a server needs "understanding," that's a sign the boundary is wrong.

The work ships in three phases:

- **Phase 1 — Documents (RAG):** answer questions from retail policy/manual documents.
- **Phase 2 — Records (structured queries):** answer questions from structured retail data (catalog, inventory, orders).
- **Phase 3 — Actions (writes):** perform state-changing operations (e.g. start a return, cancel an order) with a confirmation step.

---

## 2. Domain: Retail

*(Confirm this is your assigned industry on page 6 of the task PDF, and note the other 3 interns' industries + names — you need them for the contract.)*

What "retail" means for this project:

| Phase | Retail data | Example question |
|-------|-------------|------------------|
| 1 — Documents | Return policy, shipping policy, warranty terms, store handbook | "What's the return window for opened electronics?" |
| 2 — Records | Product catalog, inventory/stock, orders | "How many SKU12345 are in stock and what's the price?" |
| 3 — Actions | Start return, cancel order, update quantity | "Cancel order 10231." |

**Sample entities** (used across the doc and the demo):

- Product: `SKU12345` — Wireless Headphones — $79.99 — stock 42
- Product: `SKU88123` — 4K Action Camera — $249.00 — stock 0
- Order: `10231` — 1× SKU12345 — status `shipped`

---

## 3. Architecture

```
                 ┌─────────────────────────────┐
   user text ──► │        Chatbot Client        │
                 │  - LLM (qwen2.5:7b-instruct) │
                 │  - tool-call loop            │
                 │  - talks to ALL 4 servers    │
                 └──────┬───────────┬───────────┘
                        │ MCP       │ MCP
                 ┌──────▼─────┐  ┌──▼──────────┐   ...2 more interns' servers
                 │ Retail MCP │  │ Other MCP   │
                 │  server    │  │  servers    │
                 │ (no LLM)   │  │             │
                 └────────────┘  └─────────────┘
```

**Transports:** MCP supports `stdio` (local subprocess) and `HTTP`. *(Decision: use `stdio` for local dev/demo; expose `HTTP` for interop day so other interns' clients can reach your server. Confirm with the group in the contract.)*

**Chat model:** `qwen2.5:7b-instruct` via Ollama, running locally. Chosen because it reliably drives the tool-call loop (see §7 for the working transcript). Weaker models (mistral, gemma, phi) were unreliable at emitting tool calls in testing.

---

## 4. Phase 1 — Documents (RAG)

**Goal:** Answer natural-language questions grounded in retail policy documents, with citations.

**Server side (retrieval only):**

- **Documents:** *(list your source docs — return_policy.md, shipping_policy.md, warranty.md, etc.)*
- **Chunking:** *(decision — e.g. ~500 tokens/chunk, ~50 token overlap, split on headings)*
- **Embedding model:** *(decision — e.g. `nomic-embed-text` via Ollama, runs locally, no API key)*
- **Vector store:** *(decision — e.g. a local SQLite + a small vector lib, or an in-memory index)*
- **Retrieval strategy:** top-k (k = *3?*) by cosine similarity.

**Tool exposed:**

```
search_documents(query: string, k: int = 3)
  -> [ { text, source, score } ]
```

**Boundary check:** the server returns *chunks + sources*. The client's LLM writes the answer and the citation. The server never summarizes or generates.

---

## 5. Phase 2 — Records (structured queries)

**Goal:** Answer questions from structured retail data.

**Storage:** SQLite. *(Tables below — adjust.)*

- `products(sku PK, name, price, stock)`
- `orders(order_id PK, sku, quantity, status, created_at)`

**Tools exposed:**

```
lookup_product(sku: string)        -> { name, price, stock } | { error }
search_products(query: string)     -> [ { sku, name, price, stock } ]
get_order(order_id: string)        -> { order_id, sku, quantity, status } | { error }
```

**Input validation at the boundary:** validate `sku`/`order_id` format before touching the DB; use parameterized queries only (never string-concatenate SQL). Return a structured `{error: ...}` for not-found, never raise raw.

---

## 6. Phase 3 — Actions (writes)

**Goal:** Perform state-changing operations safely.

**Tools exposed:**

```
start_return(order_id: string, reason: string)  -> { return_id, status }
cancel_order(order_id: string)                  -> { order_id, status: "cancelled" }
```

**Safety design:**

- **Confirmation flow:** a write tool call is only executed after the client confirms intent with the user. *(Decision: does the server enforce a two-step confirm/commit, or does the client own confirmation? Recommend client owns the user-facing confirm; server still validates + is idempotent.)*
- **Idempotency:** cancelling an already-cancelled order returns the same result, not an error.
- **Auditability:** log every write with timestamp + args.
- **Boundary check:** the server executes the action and returns the new state. The LLM decides *whether* to call it and how to phrase the confirmation — but the server is the only thing that mutates data.

---

## 7. Chat Model & Working Tool-Call Transcript

Model: `qwen2.5:7b-instruct` (Ollama, local). Verified the full loop the client depends on — send schema → model emits tool call → run tool → feed result back → model answers:

```
MODEL: qwen2.5:7b-instruct
USER:  How many Wireless Headphones (SKU12345) are in stock, and what's the price?

TOOL CALL:   lookup_product({'sku': 'SKU12345'})
TOOL RESULT: {'name': 'Wireless Headphones', 'price': 79.99, 'stock': 42}
FINAL ANSWER: There are 42 units of Wireless Headphones (SKU12345) in stock, at $79.99 each.

PASS: full tool-call loop worked.
```

This de-risks the project's #1 failure point: an unreliable local model that can't call tools. Test script: `toolcall_test.py`.

---

## 8. Evaluation Plan

25–30 questions across categories, each with an expected answer, run through a measurement harness (accuracy + whether the right tool was called).

| Category | What it tests | Count |
|----------|---------------|-------|
| doc | Phase 1 RAG retrieval | ~6 |
| record | Phase 2 structured lookup | ~6 |
| composite | needs both a doc + a record | ~4 |
| cross-server | needs another intern's server | ~4 |
| action | Phase 3 write + confirm | ~4 |
| unanswerable | model must say "I don't know / not in data" | ~4 |

*(Full question list goes in `eval_set.md` — offer to generate it next.)*

---

## 9. Risks & Open Questions

- **Contract v1 alignment** — tool naming, transport, and error shape must match across all 4 interns. *(Biggest external dependency.)*
- **Cross-server calls** — how does the client know which server owns a question? Namespacing tools by industry?
- **Model reliability** — verified for retail tools (§7); re-test after adding more tools.
- **Confirmation ownership** for Phase 3 writes (§6).
- **Open:** *(add anything the PDF requires that's unclear.)*

---

*End of v1. Revise, fill placeholders, cut the note-to-self lines, export to PDF for submission.*
