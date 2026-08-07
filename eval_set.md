# Retail MCP — Evaluation Set v1

**Author:** (your name) — Retail intern
**Date:** 2026-08-07
**Purpose:** 28 questions to measure whether the chatbot client + Retail MCP server answer correctly. Each has an expected answer and the tool the client *should* call. The harness scores two things: (1) did it call the right tool, (2) is the answer correct.

> Placeholders in *(parens)* depend on your final documents/data — fill them once your docs and SQLite are set.

---

## Fixture data (what the answers assume)

**products**

| sku | name | price | stock |
|-----|------|-------|-------|
| SKU12345 | Wireless Headphones | 79.99 | 42 |
| SKU88123 | 4K Action Camera | 249.00 | 0 |
| SKU55010 | USB-C Cable 2m | 9.99 | 500 |
| SKU70222 | Standing Desk | 389.00 | 7 |

**orders**

| order_id | sku | quantity | status |
|----------|-----|----------|--------|
| 10231 | SKU12345 | 1 | shipped |
| 10244 | SKU88123 | 2 | processing |
| 10250 | SKU70222 | 1 | delivered |

**documents** (Phase 1 RAG): *(return_policy, shipping_policy, warranty — fill actual contents; the doc answers below assume typical retail values, adjust to match your real docs)*
- Return window: 30 days, unopened; 14 days for opened electronics.
- Free shipping over $50; standard 3–5 business days.
- Warranty: 1 year manufacturer defects.

---

## Category legend

`doc` = Phase 1 RAG · `record` = Phase 2 structured · `composite` = both · `cross-server` = needs another intern's server · `action` = Phase 3 write · `unanswerable` = must decline

---

## DOC (Phase 1 — 6)

| # | Question | Expected tool | Expected answer |
|---|----------|---------------|-----------------|
| 1 | What's the return window for unopened items? | `search_documents` | 30 days |
| 2 | How long do I have to return opened electronics? | `search_documents` | 14 days |
| 3 | What order total qualifies for free shipping? | `search_documents` | Over $50 |
| 4 | How long does standard shipping take? | `search_documents` | 3–5 business days |
| 5 | What does the warranty cover and for how long? | `search_documents` | Manufacturer defects, 1 year |
| 6 | Can I return an item after 45 days if unopened? | `search_documents` | No — window is 30 days |

## RECORD (Phase 2 — 6)

| # | Question | Expected tool | Expected answer |
|---|----------|---------------|-----------------|
| 7 | How many Wireless Headphones (SKU12345) are in stock? | `lookup_product` | 42 |
| 8 | What's the price of SKU12345? | `lookup_product` | $79.99 |
| 9 | Is the 4K Action Camera in stock? | `lookup_product` | No — 0 in stock |
| 10 | What's the status of order 10231? | `get_order` | shipped |
| 11 | How many units were in order 10244? | `get_order` | 2 |
| 12 | Find products matching "cable". | `search_products` | SKU55010, USB-C Cable 2m, $9.99 |

## COMPOSITE (needs a doc + a record — 4)

| # | Question | Expected tools | Expected answer |
|---|----------|----------------|-----------------|
| 13 | Order 10231 shipped 20 days ago — can I still return it? | `get_order` + `search_documents` | Yes — within 30-day window |
| 14 | I want to return my Standing Desk (order 10250). What's the window and is it eligible? | `get_order` + `search_documents` | Delivered; within 30 days → eligible |
| 15 | Did order 10244 qualify for free shipping? | `get_order` + `lookup_product` + `search_documents` | 2 × $249 = $498 > $50 → yes |
| 16 | Is the Action Camera worth ordering if it's out of stock — what's the warranty? | `lookup_product` + `search_documents` | Out of stock now; 1-yr warranty |

## CROSS-SERVER (needs another intern's server — 4)

*(Fill exact expected answers after Contract v1 — you need to know the other 3 industries. Placeholders below.)*

| # | Question | Expected | Notes |
|---|----------|----------|-------|
| 17 | *(question spanning retail + intern 2's domain)* | *(depends)* | Routes to intern 2's server |
| 18 | *(question spanning retail + intern 3's domain)* | *(depends)* | Routes to intern 3's server |
| 19 | *(question spanning retail + intern 4's domain)* | *(depends)* | Routes to intern 4's server |
| 20 | *(question needing 2 servers at once)* | *(depends)* | Tests multi-server orchestration |

## ACTION (Phase 3 write + confirm — 4)

| # | Question | Expected tool | Expected behavior |
|---|----------|---------------|-------------------|
| 21 | Cancel order 10244. | `cancel_order` | Confirm first, then status → cancelled |
| 22 | Start a return for order 10231, reason "changed my mind". | `start_return` | Confirm first, then return_id + status |
| 23 | Cancel order 10250 (already delivered). | `cancel_order` | Should refuse/flag — can't cancel delivered |
| 24 | Cancel order 10244, then cancel it again. | `cancel_order` | Idempotent — 2nd call returns same cancelled state, no error |

## UNANSWERABLE (must decline — 4)

| # | Question | Expected tool | Expected answer |
|---|----------|---------------|-----------------|
| 25 | What's the CEO's home address? | none | Decline — not in data |
| 26 | How many SKU99999 are in stock? | `lookup_product` | Not found — no such SKU |
| 27 | What will stock be next month? | none | Can't predict — not in data |
| 28 | What's the status of order 99999? | `get_order` | Not found — no such order |

---

## Scoring harness (what to build)

For each question: run it through the client, capture `(tool_called, final_answer)`.

- **Tool score:** did `tool_called` match `expected_tool`? (1/0)
- **Answer score:** does `final_answer` contain the expected value? (exact-match or keyword contains; manual check for composite)
- **Report:** accuracy per category + overall. Track across interop days to show improvement.

*(Harness can be a small Python script that loops this list — offer to scaffold `run_evals.py` when you start Phase 1 build.)*
