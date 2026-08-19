# Evaluation Scorecard - Retail / E-commerce (Intern 3)

Generated 2026-08-19 13:38:14 +04 by `eval/harness.py`. Phase 1 (Documents) + Phase 2 (Records).

| Run parameter | Value |
|---|---|
| Ground truth | `eval/ground_truth.json` |
| Chroma path | `/Users/rishi/Desktop/TOPAZ MCP CHATBOT /data/chroma` |
| Embedding model | `BAAI/bge-m3` (local, CPU; never on GB10) |
| Model load (one-off) | 21106 ms |
| Query prefix | none |
| top_k | 5 |
| Token counting | tiktoken cl100k_base (GPT-family proxy) |
| Strategies | heading -> `retail_docs` (97 chunks), packed -> `retail_docs_packed` (33 chunks) |

## Read this before reading any percentage

**n = 11.** Every recall figure below is over **11 scoreable questions**, not the 28 in `eval/eval_set.md`. One question is worth **9.09 percentage points**, so a single miss moves Recall@5 by roughly 9 points. A recall percentage quoted without its n is misleading, which is why n is printed beside every figure in this document.

The other 17 questions are records, cross-server, actions and unanswerables. They are not silently dropped: they appear in the scorecard below marked `n/a - needs phase 2`, `n/a - needs phase 3` or `n/a - needs client`.

At n=11: Recall@5 >= 85% allows at most **1 miss** (10/11 = 90.9% passes, 9/11 = 81.8% fails). Recall@1 >= 60% allows at most **4 misses** (7/11 = 63.6%).

## Scorecard

| Metric | How measured | Target | heading | packed | Verdict |
|---|---|---|---|---|---|
| Recall@5 (documents) | any expected doc anywhere in top-5, n=11 | >= 85% | 100.0% (11/11) | 100.0% (11/11) | **PASS** |
| Recall@1 (documents) | top-ranked result is an expected doc, n=11 | >= 60% | 90.9% (10/11) | 100.0% (11/11) | **PASS** |
| Records: query correctness | exact lookup and filtering over SQLite, n=11 | >= 90% | 100.0% (11/11) | 100.0% (11/11) | **PASS** |
| Records: numerical accuracy | exact amounts, totals, and counts matching ground truth | 100% | 100.0% | 100.0% | **PASS** |
| Records: empty-result honesty | empty result for non-existent order (Q28) | 100% | 100.0% (Q28) | 100.0% (Q28) | **PASS** |
| Routing: correct server | client router, not built | >= 90% | - | - | n/a - needs client |
| Routing: correct tool type | client router, not built | >= 90% | - | - | n/a - needs client |
| Routing: spurious calls | client tool-call loop, not built | <= 1/query | - | - | n/a - needs client |
| Routing: cross-server synthesis | needs 2+ interns' servers | >= 80% | - | - | n/a - needs client |
| Routing: composite handling | needs documents + records in one answer | >= 80% | - | - | n/a - needs client |
| Answer quality: groundedness | needs generated answers | 100% | - | - | n/a - needs client |
| Answer quality: citation accuracy | needs generated answers | 100% | - | - | n/a - needs client |
| Answer quality: correct refusal | needs generated answers (Q5, Q26-28) | 100% | - | - | n/a - needs client |
| Answer quality: false refusal | needs generated answers | <= 10% | - | - | n/a - needs client |
| Action safety: spurious writes | phase-3 write tools not built | 0 | - | - | n/a - needs phase 3 |
| Action safety: fabricated fields | phase-3 write tools not built | 0 | - | - | n/a - needs phase 3 |
| Action safety: correct action routing | phase-3 write tools not built | 100% | - | - | n/a - needs phase 3 |
| Action safety: confirmation shown | phase-3 write tools not built | 100% | - | - | n/a - needs phase 3 |
| Latency: query embedding, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 69.5 ms | 32.3 ms | - |
| Latency: query embedding, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 301.1 ms | 33.9 ms | - |
| Latency: vector search, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 5.6 ms | 4.3 ms | - |
| Latency: vector search, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 13.4 ms | 7.1 ms | - |
| Latency: retrieval total, WARM p50 | embed + search, cold query discarded, n=10 | <= 300 ms | 73.8 ms | 36.6 ms | **PASS** |
| Latency: retrieval total, WARM p95 | embed + search, cold query discarded, n=10 | <= 300 ms | 308.4 ms | 38.5 ms | heading: **FAIL** / packed: **PASS** |
| Latency: retrieval total, COLD | first query after model load (Q1), 1 sample | reported separately, no gate | 595.4 ms (embed 587.0 + search 8.3) | 35.1 ms (embed 33.0 + search 2.0) | - |
| Latency: end-to-end p50 | needs the client + chat model | <= 4 s | - | - | n/a - needs client |
| Latency: end-to-end p95 | needs the client + chat model | <= 10 s | - | - | n/a - needs client |
| Latency: MCP transport overhead | needs the MCP server | <= 100 ms | - | - | n/a - needs phase 1 server |
| Latency: structured query, WARM p50 | direct SQLite query execution time, n=11 | <= 100 ms | 0.21 ms | 0.21 ms | **PASS** |
| Latency: structured query, WARM p95 | direct SQLite query execution time, n=11 | <= 100 ms | 7.01 ms | 7.01 ms | **PASS** |
| Tokens: NAIVE BASELINE (compact) | verbatim top-5 tool result, compact JSON, mean n=11 | BASELINE - the number to beat | 685 tokens/query | 1234 tokens/query | BASELINE |
| Tokens: NAIVE BASELINE (verbose) | verbatim top-5 tool result, indented JSON, mean n=11 | BASELINE - worst case | 860 tokens/query | 1410 tokens/query | BASELINE |
| Tokens: reduction vs NAIVE BASELINE | needs the compaction layer, not built | >= 40% cut | - | - | n/a - needs client |
| Robustness suite (9 cases) | needs a running server + client | no crashes | - | - | n/a - needs client |

**Measured winner: `packed`** — `packed` tied on Recall@5 with `heading`, so the tie was broken on Recall@1 (100.0% vs 90.9%); heading excluded: p95 latency > 300 ms. Winner decided by Recall@5, latency gate (p95 ≤ 300 ms), then Recall@1 — not by preference.

### Per-question detail - Structured Records (n=11)

| # | Question | Tool Called | Arguments | Latency | Status |
|---|---|---|---|---|---|
| 8 | status of order ORD-9021? | `kb_retail_query_orders` | `order_id='ORD-9021'` | 7.01 ms | **PASS** |
| 9 | did order ORD-9021 actually ship? | `kb_retail_query_shipments` | `order_id='ORD-9021'` | 0.45 ms | **PASS** |
| 10 | list open returns for customer CUST-103 | `kb_retail_query_returns` | `customer_id='CUST-103', status='refund_processing'` | 0.20 ms | **PASS** |
| 11 | how many orders has Alex Rivera (CUST-101) placed this year? | `kb_retail_query_customer` | `customer_id='CUST-101'` | 0.50 ms | **PASS** |
| 12 | how much has Marcus Vance (CUST-103) been refunded this year? | `kb_retail_query_customer` | `customer_id='CUST-103'` | 0.27 ms | **PASS** |
| 13 | which line items in order ORD-9021 were delivered? | `kb_retail_query_shipments` | `order_id='ORD-9021'` | 0.22 ms | **PASS** |
| 14 | I was charged twice — is that allowed and did it actually happen? (record half) | `kb_retail_query_orders` | `customer_id='CUST-101'` | 0.21 ms | **PASS** |
| 15 | can they return order ORD-9031 — what's the window and is it eligible? (record half) | `kb_retail_query_orders` | `order_id='ORD-9031'` | 0.19 ms | **PASS** |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (record half) | `kb_retail_query_shipments` | `order_id='ORD-9021'` | 0.20 ms | **PASS** |
| 17 | refund on return RET-701 — how long should it take and did it go through? (record half) | `kb_retail_query_returns` | `return_id='RET-701'` | 0.18 ms | **PASS** |
| 28 | status of order ORD-99999999? | `kb_retail_query_orders` | `order_id='ORD-99999999'` | 0.16 ms | **PASS** |

### Per-question detail - Document Retrieval `heading` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `amazon/refund_timelines.md` | Y | Y | 595.4 *(cold)* | 684 | 859 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 242.7 | 697 | 872 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 308.4 | 596 | 771 |
| 4 | what's covered under warranty and for how long? | `ikea/warranty_terms.md` | Y | Y | 47.8 | 915 | 1090 |
| 5 | they want to return after 40 days, are we allowed? | `amazon/returns.md` | Y | Y | 43.8 | 619 | 794 |
| 6 | returns window AND who pays return shipping? | `amazon/returns.md` | Y | Y | 241.3 | 613 | 788 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 184.5 | 686 | 861 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 149.6 | 739 | 915 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 73.8 | 591 | 767 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `amazon/charged_twice.md` | n | Y | 65.6 | 698 | 874 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 73.1 | 693 | 869 |
### Per-question detail - Document Retrieval `packed` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `amazon/refund_timelines.md` | Y | Y | 35.1 *(cold)* | 1176 | 1351 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 32.8 | 1153 | 1328 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 36.0 | 1282 | 1457 |
| 4 | what's covered under warranty and for how long? | `ikea/warranty_terms.md` | Y | Y | 36.7 | 1184 | 1359 |
| 5 | they want to return after 40 days, are we allowed? | `bestbuy/returns.md` | Y | Y | 35.3 | 1278 | 1453 |
| 6 | returns window AND who pays return shipping? | `amazon/returns.md` | Y | Y | 34.8 | 1278 | 1453 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 38.3 | 1232 | 1407 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 36.6 | 1227 | 1403 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 36.8 | 1270 | 1446 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `target/delivery.md` | Y | Y | 38.5 | 1196 | 1372 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 36.9 | 1303 | 1479 |
## How to read this scorecard

- **Retrieval only.** No chat LLM is called by this harness, and none will be called by the server. Rows needing generated answers, records, actions or another intern's server are marked `n/a` and left in the table, so the coverage gap is visible rather than implied.
- **COLD vs WARM.** Each strategy runs a warmup query (embed + search, discarded) before scoring, so the cold row is a fair per-strategy measurement rather than an artifact of which strategy loaded the model. p95 over 10 warm samples is the nearest-rank value, i.e. the maximum observed - indicative, not tight.
- **Two token baselines.** Compact JSON (minimal separators) is the honest floor; verbose JSON (indented) is the worst-case ceiling. The >= 40% reduction target is measured against the compact baseline.
- **Winner selection.** The winner is decided by: (1) Recall@5, (2) latency p95 <= 300 ms gate, (3) Recall@1 tiebreaker, in that order. A strategy that fails the latency gate cannot be the winner unless every strategy fails it.
- **Exit code** reports whether the harness ran, not whether the targets passed. A FAIL row is a measurement, not a crash.

