# Baseline Scorecard - Retail / E-commerce (Intern 3)

Generated 2026-08-13 16:16:23 +04 by `eval/harness.py`. Phase 1 (documents) only, retrieval only.

| Run parameter | Value |
|---|---|
| Ground truth | `eval/ground_truth.json` |
| Chroma path | `/Users/rishi/Desktop/TOPAZ MCP CHATBOT /data/chroma` |
| Embedding model | `BAAI/bge-small-en-v1.5` (local, CPU; never on GB10) |
| Model load (one-off) | 5808 ms |
| Query prefix | none |
| top_k | 5 |
| Token counting | tiktoken cl100k_base (GPT-family proxy) |
| Strategies | heading -> `retail_docs_heading` (97 chunks), packed -> `retail_docs_packed` (33 chunks) |

## Read this before reading any percentage

**n = 11.** Every recall figure below is over **11 scoreable questions**, not the 28 in `eval/eval_set.md`. One question is worth **9.09 percentage points**, so a single miss moves Recall@5 by roughly 9 points. A recall percentage quoted without its n is misleading, which is why n is printed beside every figure in this document.

The other 17 questions are records, cross-server, actions and unanswerables. They are not silently dropped: they appear in the scorecard below marked `n/a - needs phase 2`, `n/a - needs phase 3` or `n/a - needs client`.

At n=11: Recall@5 >= 85% allows at most **1 miss** (10/11 = 90.9% passes, 9/11 = 81.8% fails). Recall@1 >= 60% allows at most **4 misses** (7/11 = 63.6%).

## Scorecard

| Metric | How measured | Target | heading | packed | Verdict |
|---|---|---|---|---|---|
| Recall@5 (documents) | any expected doc anywhere in top-5, n=11 | >= 85% | 100.0% (11/11) | 100.0% (11/11) | **PASS** |
| Recall@1 (documents) | top-ranked result is an expected doc, n=11 | >= 60% | 90.9% (10/11) | 81.8% (9/11) | **PASS** |
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
| Latency: query embedding, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 15.9 ms | 14.2 ms | - |
| Latency: query embedding, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 43.8 ms | 15.4 ms | - |
| Latency: vector search, WARM p50 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 0.9 ms | 0.7 ms | - |
| Latency: vector search, WARM p95 | timed as its own stage, nearest-rank, n=10 | part of the <= 300 ms retrieval budget | 2.3 ms | 0.9 ms | - |
| Latency: retrieval total, WARM p50 | embed + search, cold query discarded, n=10 | <= 300 ms | 16.8 ms | 14.9 ms | **PASS** |
| Latency: retrieval total, WARM p95 | embed + search, cold query discarded, n=10 | <= 300 ms | 46.0 ms | 16.3 ms | **PASS** |
| Latency: retrieval total, COLD | first query after model load (Q1), 1 sample | reported separately, no gate | 54.1 ms (embed 51.4 + search 2.7) | 16.0 ms (embed 15.2 + search 0.8) | - |
| Latency: end-to-end p50 | needs the client + chat model | <= 4 s | - | - | n/a - needs client |
| Latency: end-to-end p95 | needs the client + chat model | <= 10 s | - | - | n/a - needs client |
| Latency: MCP transport overhead | needs the MCP server | <= 100 ms | - | - | n/a - needs phase 1 server |
| Latency: structured query | needs the phase-2 SQLite tools | <= 100 ms | - | - | n/a - needs phase 2 |
| Tokens: NAIVE BASELINE (compact) | verbatim top-5 tool result, compact JSON, mean n=11 | BASELINE - the number to beat | 586 tokens/query | 1122 tokens/query | BASELINE |
| Tokens: NAIVE BASELINE (verbose) | verbatim top-5 tool result, indented JSON, mean n=11 | BASELINE - worst case | 731 tokens/query | 1268 tokens/query | BASELINE |
| Tokens: reduction vs NAIVE BASELINE | needs the compaction layer, not built | >= 40% cut | - | - | n/a - needs client |
| Robustness suite (9 cases) | needs a running server + client | no crashes | - | - | n/a - needs client |

**Measured winner: `heading`** — `heading` tied on Recall@5 with `packed`, so the tie was broken on Recall@1 (90.9% vs 81.8%). Winner decided by Recall@5, latency gate (p95 ≤ 300 ms), then Recall@1 — not by preference.

### Per-question detail - `heading` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `bestbuy/returns.md` | Y | Y | 54.1 *(cold)* | 561 | 706 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 46.0 | 656 | 801 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 39.8 | 531 | 676 |
| 4 | what's covered under warranty and for how long? | `amazon/warranty.md` | Y | Y | 20.6 | 723 | 868 |
| 5 | they want to return after 40 days, are we allowed? | `ikea/returns.md` | n | Y | 16.8 | 543 | 688 |
| 6 | returns window AND who pays return shipping? | `target/returns.md` | Y | Y | 15.0 | 492 | 637 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 11.7 | 552 | 697 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 41.1 | 606 | 752 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 43.6 | 547 | 693 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `amazon/charged_twice.md` | Y | Y | 16.8 | 634 | 780 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 15.0 | 600 | 746 |

### Per-question detail - `packed` (n=11)

| # | Question | Top-1 retrieved | @1 | @5 | Retrieval ms | Tokens (compact) | Tokens (verbose) |
|---|---|---|---|---|---|---|---|
| 1 | how long till they get their money back on a return? | `amazon/refund_timelines.md` | Y | Y | 16.0 *(cold)* | 1083 | 1228 |
| 2 | customer's parcel never showed up — what's our process? | `amazon/order_tracking.md` | Y | Y | 14.8 | 1090 | 1235 |
| 3 | can they send back opened electronics? | `target/returns.md` | Y | Y | 15.6 | 1158 | 1303 |
| 4 | what's covered under warranty and for how long? | `amazon/warranty.md` | Y | Y | 16.3 | 1091 | 1236 |
| 5 | they want to return after 40 days, are we allowed? | `ikea/returns.md` | n | Y | 15.4 | 1199 | 1344 |
| 6 | returns window AND who pays return shipping? | `ikea/returns.md` | n | Y | 16.1 | 1172 | 1317 |
| 7 | does every store charge a 'restocking fee' on returns? | `bestbuy/returns.md` | Y | Y | 13.4 | 1007 | 1152 |
| 14 | I was charged twice — is that allowed and did it actually happen? (document half only) | `amazon/charged_twice.md` | Y | Y | 14.9 | 1101 | 1247 |
| 15 | can they return order [REF] — what's the window and is it eligible? (document half only) | `amazon/returns.md` | Y | Y | 13.7 | 1173 | 1319 |
| 16 | parcel split into two — is partial delivery covered, and what shipped? (document half only) | `amazon/charged_twice.md` | Y | Y | 13.4 | 1107 | 1253 |
| 17 | refund on [REF] — how long should it take and did it go through? (document half only) | `amazon/refund_timelines.md` | Y | Y | 16.0 | 1164 | 1310 |

## How to read this scorecard

- **Retrieval only.** No chat LLM is called by this harness, and none will be called by the server. Rows needing generated answers, records, actions or another intern's server are marked `n/a` and left in the table, so the coverage gap is visible rather than implied.
- **COLD vs WARM.** Each strategy runs a warmup query (embed + search, discarded) before scoring, so the cold row is a fair per-strategy measurement rather than an artifact of which strategy loaded the model. p95 over 10 warm samples is the nearest-rank value, i.e. the maximum observed - indicative, not tight.
- **Two token baselines.** Compact JSON (minimal separators) is the honest floor; verbose JSON (indented) is the worst-case ceiling. The >= 40% reduction target is measured against the compact baseline.
- **Winner selection.** The winner is decided by: (1) Recall@5, (2) latency p95 <= 300 ms gate, (3) Recall@1 tiebreaker, in that order. A strategy that fails the latency gate cannot be the winner unless every strategy fails it.
- **Exit code** reports whether the harness ran, not whether the targets passed. A FAIL row is a measurement, not a crash.

