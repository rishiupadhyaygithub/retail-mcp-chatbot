# Baseline Scorecard - Retail / E-commerce (Intern 3)

Generated 2026-08-18 14:08:18 +04 by `eval/harness.py`. Phase 1 (documents) only, retrieval only.

| Run parameter | Value |
|---|---|
| Ground truth | `eval/ground_truth.json` |
| Chroma path | `/Users/rishi/Desktop/TOPAZ MCP CHATBOT /data/chroma` |
| Embedding model | `BAAI/bge-m3` (local, CPU; never on GB10) |
| Model load (one-off) | 24371 ms |
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
| Recall@1 (documents) | top-ranked result is an expected doc, n=11 | >= 60% | 100.0% (11/11) | 90.9% (10/11) | **PASS** |
| Routing: correct server | client router, not built | >= 90% | - | - | n/a - needs client |
| Routing: correct tool type | client router, not built | >= 90% | - | - | n/a - needs client |
| Routing: spurious calls | client tool-call loop, not built | <= 1/query | - | - | n/a - needs client |
| Routing: cross-server synthesis | needs 2+ interns' servers | >= 80% | - | - | n/a - needs client |
| Routing: composite handling | needs documents + records in one answer | >= 80% | - | - | n/a - needs phase 2 |
| Records: query correctness | SQLite dataset not built | >= 90% | - | - | n/a - needs phase 2 |
| Records: numerical accuracy | SQLite dataset not built | 100% | - | - | n/a - needs phase 2 |
| Records: empty-result honesty | SQLite dataset not built | 100% | - | - | n/a - needs phase 2 |
| Answer quality: groundedness | needs generated answers | 100% | - | - | n/a - needs client |
| Answer quality: citation accuracy | needs generated answers | 100% | - | - | n/a - needs client |
| Answer quality: correct refusal | needs generated answers (Q5, Q26-28) | 100% | - | - | n/a - needs client |
| Answer quality: false refusal | needs generated answers | <= 10% | - | - | n/a - needs client |
| Action safety: spurious writes | phase-3 write tools not built | 0 | - | - | n/a - needs phase 3 |
| Action safety: fabricated fields | phase-3 write tools not built | 0 | - | - | n/a - needs phase 3 |
| Action safety: correct action routing | phase-3 write tools not built | 100% | - | - | n/a - needs phase 3 |
| Action safety: confirmation shown | phase-3 write tools not built | 100% | - | - | n/a - needs phase 3 |
| Latency: query embedding, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 59.9 ms | 29.9 ms | - |
| Latency: query embedding, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 129.2 ms | 33.5 ms | - |
| Latency: vector search, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 2.4 ms | 1.8 ms | - |
| Latency: vector search, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 4.9 ms | 2.3 ms | - |
| Latency: retrieval total, WARM p50 | embed + search, cold query discarded, n=10 | <= 300 ms | 62.1 ms | 32.1 ms | **PASS** |
| Latency: retrieval total, WARM p95 | embed + search, cold query discarded, n=10 | <= 300 ms | 134.1 ms | 35.3 ms | **PASS** |
| Latency: retrieval total, COLD | first query after model load (Q1), 1 sample | reported separately, no gate | 127.0 ms (embed 122.2 + search 4.8) | 33.5 ms (embed 31.1 + search 2.5) | - |
| Latency: end-to-end p50 | needs the client + chat model | <= 4 s | - | - | n/a - needs client |
| Latency: end-to-end p95 | needs the client + chat model | <= 10 s | - | - | n/a - needs client |
| Latency: MCP transport overhead | needs the MCP server | <= 100 ms | - | - | n/a - needs phase 1 server |
| Latency: structured query | needs the phase-2 SQLite tools | <= 100 ms | - | - | n/a - needs phase 2 |
| Tokens: NAIVE BASELINE (compact) | verbatim top-5 tool result, compact JSON, mean n=11 | BASELINE - the number to beat | 685 tokens/query | 1234 tokens/query | BASELINE |
| Tokens: NAIVE BASELINE (verbose) | verbatim top-5 tool result, indented JSON, mean n=11 | BASELINE - worst case | 860 tokens/query | 1410 tokens/query | BASELINE |
| Tokens: reduction vs NAIVE BASELINE | needs the compaction layer, not built | >= 40% cut | - | - | n/a - needs client |
| Robustness suite (9 cases) | needs a running server + client | no crashes | - | - | n/a - needs client |

**Measured winner: `heading`** — `heading` tied on Recall@5 with `packed`, so the tie was broken on Recall@1 (100.0% vs 90.9%). Winner decided by Recall@5, latency gate (p95 ≤ 300 ms), then Recall@1 — not by preference.

### Per-question detail - `heading` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `amazon/refund_timelines.md` | Y | Y | 127.0 *(cold)* | 684 | 859 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 69.9 | 697 | 872 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 63.9 | 596 | 771 |
| 4 | what's covered under warranty and for how long? | `ikea/warranty_terms.md` | Y | Y | 38.7 | 915 | 1090 |
| 5 | they want to return after 40 days, are we allowed? | `amazon/returns.md` | Y | Y | 36.4 | 619 | 794 |
| 6 | returns window AND who pays return shipping? | `amazon/returns.md` | Y | Y | 64.3 | 613 | 788 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 134.1 | 686 | 861 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 68.9 | 739 | 915 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 61.3 | 591 | 767 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `amazon/charged_twice.md` | Y | Y | 56.9 | 698 | 874 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 62.1 | 693 | 869 |

### Per-question detail - `packed` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `amazon/refund_timelines.md` | Y | Y | 33.5 *(cold)* | 1176 | 1351 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 32.1 | 1153 | 1328 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 30.9 | 1282 | 1457 |
| 4 | what's covered under warranty and for how long? | `ikea/warranty_terms.md` | Y | Y | 31.9 | 1184 | 1359 |
| 5 | they want to return after 40 days, are we allowed? | `bestbuy/returns.md` | Y | Y | 31.0 | 1278 | 1453 |
| 6 | returns window AND who pays return shipping? | `amazon/returns.md` | Y | Y | 31.4 | 1278 | 1453 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 32.8 | 1232 | 1407 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 33.2 | 1227 | 1403 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 35.3 | 1270 | 1446 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `target/delivery.md` | n | Y | 35.3 | 1196 | 1372 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 32.4 | 1303 | 1479 |

## How to read this scorecard

- **Retrieval only.** No chat LLM is called by this harness, and none will be called by the server. Rows needing generated answers, records, actions or another intern's server are marked `n/a` and left in the table, so the coverage gap is visible rather than implied.
- **COLD vs WARM.** Each strategy runs a warmup query (embed + search, discarded) before scoring, so the cold row is a fair per-strategy measurement rather than an artifact of which strategy loaded the model. p95 over 10 warm samples is the nearest-rank value, i.e. the maximum observed - indicative, not tight.
- **Two token baselines.** Compact JSON (minimal separators) is the honest floor; verbose JSON (indented) is the worst-case ceiling. The >= 40% reduction target is measured against the compact baseline.
- **Winner selection.** The winner is decided by: (1) Recall@5, (2) latency p95 <= 300 ms gate, (3) Recall@1 tiebreaker, in that order. A strategy that fails the latency gate cannot be the winner unless every strategy fails it.
- **Exit code** reports whether the harness ran, not whether the targets passed. A FAIL row is a measurement, not a crash.

