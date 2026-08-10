# Interop Contract v1 — 4-Intern MCP Servers

**Drafted by:** (your name) — Retail intern
**Date:** 2026-08-07
**Status:** DRAFT — bring to the other 3 interns, agree together, then everyone commits to it.

> This is the shared agreement so all 4 servers speak the same shape and one client can talk to all of them. It is a *starter* — the numbers and names in *(parens)* are proposals to debate as a group, not decisions I made for you. Goal of the meeting: turn every *(paren)* into an agreed value.

---

## 0. Who owns what

| Intern | Name | Industry | Server name / prefix |
|--------|------|----------|----------------------|
| 1 | *(you?)* | Retail | `retail` |
| 2 | *(name)* | *(industry)* | *(prefix)* |
| 3 | *(name)* | *(industry)* | *(prefix)* |
| 4 | *(name)* | *(industry)* | *(prefix)* |

*(Fill from page 6 of the task PDF. This table is the first thing to nail down — everything else depends on it.)*

---

## 1. Transport

- All servers expose **`stdio`** for local dev.
- All servers ALSO expose **`HTTP`** for interop day, so one client can reach all four over the network.
- HTTP base URL format: *(propose — e.g. `http://<host>:<port>/mcp`, each intern picks a port)*
- **Proposed:** every intern runs on a distinct port. Retail = *(8001?)*, Intern 2 = *(8002?)*, etc.

---

## 2. Tool naming convention

**Namespace every tool with the industry prefix** so the client can tell servers apart and route correctly.

Format: `<prefix>_<verb>_<noun>`

| Server | Example tools |
|--------|---------------|
| retail | `retail_search_documents`, `retail_lookup_product`, `retail_get_order`, `retail_cancel_order` |
| *(intern 2)* | `<prefix>_search_documents`, ... |

**Agreement needed:** everyone uses the same verbs for the same *kind* of operation, so the client's logic is uniform:

- Phase 1 doc search → `<prefix>_search_documents`
- Phase 2 record lookup → `<prefix>_lookup_<entity>` / `<prefix>_get_<entity>` / `<prefix>_search_<entity>`
- Phase 3 write → `<prefix>_<action>` (e.g. `_cancel_order`, `_start_return`)

---

## 3. Shared response shapes

Every tool returns JSON. **Success** and **error** have a fixed shape across all servers so the client handles them uniformly.

**Success:**
```json
{ "ok": true, "data": { ... } }
```

**Error:**
```json
{ "ok": false, "error": { "code": "NOT_FOUND", "message": "human-readable reason" } }
```

**Agreed error codes** *(propose this set)*:

| code | meaning |
|------|---------|
| `NOT_FOUND` | entity doesn't exist |
| `INVALID_INPUT` | bad/missing argument |
| `NOT_ALLOWED` | action forbidden (e.g. cancel a delivered order) |
| `CONFLICT` | state conflict (e.g. already cancelled) |

> Rule everyone agrees to: **a "not found" is a normal error response, never a crash.** No raw exceptions across the wire.

---

## 4. Document search contract (Phase 1)

`<prefix>_search_documents(query: string, k: int = 3)`

Returns:
```json
{ "ok": true, "data": { "results": [
  { "text": "chunk text", "source": "return_policy.md", "score": 0.83 }
] } }
```

- `source` is required on every chunk so the client can cite.
- `score` is optional but recommended.

---

## 5. The core rule (all servers must honor)

> **Servers do retrieval and data only. No server calls an LLM.**
> All reasoning, planning, tool selection, and text generation happen in the client.

Any server that "understands" or "summarizes" internally violates the contract. If you feel you need an LLM in the server, the tool boundary is wrong — raise it in the group.

---

## 6. Phase 3 write safety (all servers)

- Writes are **idempotent** where possible (repeating a cancel returns the same state, not an error).
- Writes **validate input** and return `NOT_ALLOWED` / `CONFLICT` rather than mutating badly.
- **Confirmation is owned by the client** (it confirms with the user before calling the write tool). Servers still validate independently — never trust the client blindly.
- Servers **log every write** (timestamp + args) for the audit trail.

---

## 7. Versioning

- This is **v1**. After Phase 1 interop day, we write a **design addendum + Contract v2** with what we learned.
- Breaking changes require group agreement + a version bump. No silent shape changes.

---

## 8. Open questions for the meeting

1. Confirm the intern/industry table (§0).
2. Ports for HTTP (§1).
3. Do we all agree on the success/error envelope (§3)? Any missing error codes?
4. How does the client discover which server owns a question — by prefix, by asking each server, or a routing map? *(This is the trickiest cross-server design call.)*
5. Shared embedding model for Phase 1, or each intern picks their own? (Doesn't have to match, but worth deciding.)

---

*Bring this, fill the parens together, everyone commits. That's Contract v1 done.*
