# Interop Contract v1 — 4-Intern MCP Servers

**Status:** DRAFT for joint agreement. Lives in the shared repo, jointly owned. Frozen on agreement; changes by consensus only, additive where possible.
**Scope of v1:** phase-1 document search, plus resources, prompts, errors, transport, addresses. (Query + action tools are added in **v2** before phase-2 build.)

> **[AGREE]** = must be settled by all four interns before freeze. **[TODO]** = a value an intern fills for their own row.

---

## 0. Who owns what

| Intern | Industry | Prefix | Action (v2) |
|--------|----------|--------|-------------|
| 1 | Banking | `kb_banking` | raise a transaction dispute |
| 2 | Hospitality | `kb_hospitality` | log a guest complaint |
| 3 (Rishi) | Retail / e-commerce | `kb_retail` | open a return / RMA |
| 4 | Telecommunications | `kb_telecom` | raise a fault ticket |

*(Confirm prefixes read the same for everyone — the client routes on them.)*

---

## 1. Transport & network

- Every server exposes **both** `stdio` **and** streamable **HTTP**, switchable by config. HTTP is what the other three clients use; stdio would force them to subprocess your server with all your deps.
- Bind to the **machine's network interface, not `localhost`**. Open the port in the local firewall.
- Record host IP + port here; tell everyone if it changes.

| Intern | Host IP | Port |
|--------|---------|------|
| 1 Banking | [TODO] | [TODO] |
| 2 Hospitality | [TODO] | [TODO] |
| 3 Retail | [TODO] | [TODO] |
| 4 Telecom | [TODO] | [TODO] |

---

## 2. Tool naming

Four servers all exposing `search` gives the client four indistinguishable tools. Convention: `kb_<industry>_<verb>[_<noun>]`.

| Phase | Retail example | Pattern |
|-------|----------------|---------|
| 1 search | `kb_retail_search` | `kb_<industry>_search` |
| 2 query | `kb_retail_query_orders` | `kb_<industry>_query_<entity>` |
| 3 action | `kb_retail_open_return` | `kb_<industry>_<action>` |

**Descriptions are part of the contract.** The `description` is how the LLM picks both the server *and* the tool type. A vague description means the tool never gets called, or gets called for the wrong thing. Each intern writes descriptions that disambiguate industry + tool type. **[AGREE]** a house style for descriptions (e.g. "Search <Industry> policy/help docs. Use for 'what is the policy' questions, not specific-account lookups.").

---

## 3. Search: input & output (phase 1)

**Input:** `query` (string, required), `top_k` (int, default 5), plus optional `filters`.

**Output — identical across all four servers:**

```json
{
  "results": [
    {
      "content": "the passage text",
      "source": "document title",
      "section": "heading, if available",
      "score": 0.82,
      "chunk_id": "retail-doc-4:chunk-12"
    }
  ],
  "query": "the query as received",
  "total_found": 5
}
```

**Empty results:** a success response with an empty `results` array — **not** an error, **not** a 404. The client must be able to pass "I searched and found nothing" to the model verbatim. Same for a query returning zero rows (v2).

---

## 4. Errors — one agreed shape

**[AGREE]** a single error shape used by all four servers for every failure (malformed input, not-found, capability-not-honoured). Proposed:

```json
{ "error": { "code": "INVALID_INPUT", "message": "human-readable reason" } }
```

Proposed codes: `INVALID_INPUT`, `NOT_FOUND`, `NOT_ALLOWED`, `CONFLICT`, `INTERNAL`. A malformed tool argument returns this shape — never a stack trace, never a hang.

---

## 5. Resources & prompts (phase 1)

Each server exposes at least **one resource** (a document list; the data schema is a good second) and at least **one prompt** template. **[AGREE]** whether resource/prompt names also follow the `kb_<industry>_` convention.

---

## 6. Query tools (v2 — placeholder, agreed before phase-2 build)

Common envelope for tabular results, agreed by all four:

- a **columns** list, and **rows** as bare arrays (not repeated per-row keys) — spends field names once, not once per row.
- a **total count** and a **truncation flag**.
- an agreed **maximum row count** — an unbounded query tool blows the model's context window.

Parameterised, typed tools (e.g. `kb_retail_query_orders(customer_ref, from_date, to_date, status)`) — **never text-to-SQL**.

Proposed shape (**[AGREE]** in v2):
```json
{ "columns": ["ref","amount","status"], "rows": [["...","...","..."]],
  "total": 128, "truncated": true }
```

---

## 7. Action tool (v2 — placeholder)

Each intern's one write tool. **[AGREE]**: name pattern, required + optional fields, and what it returns (a reference). A client must raise a case against any of the four servers without special-casing. **Missing required field → an error, never a default.**

---

## 8. The rule all servers honour

> **No server calls an LLM.** Retrieval and lookup only. All generation happens in the host. A server that "summarises" or "understands" internally violates the contract.

---

## 9. Conformance (interop day)

Every client tests all three other servers against this contract and files one short report per server in the shared repo. Minimum checks: initialization + capability declaration; tool schemas match; empty results = success + empty array; declared resources/prompts work; malformed input → agreed error shape (no stack trace, no hang); server survives client disconnect/reconnect.

---

## 10. Versioning

- **v1** — this document, with the design documents.
- **v2** — before phase-2 build: adds §6 query tools and §7 action tool.
- Frozen on agreement. Changes by consensus, additively where possible. Extending a contract without breaking three other clients is part of the exercise.

---

## 11. Open items for the meeting

1. Fill §0 prefixes + §1 IP/port table.
2. Freeze §4 error shape + codes.
3. §2 description house style.
4. How the client discovers which server owns a question (prefix routing vs asking each server) — the trickiest cross-server call.
5. Shared dates: interop day + all three demos (must be identical across all four plans).
