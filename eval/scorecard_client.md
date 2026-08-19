# Scorecard — client layer (routing, answer quality, latency)

> **STALE — DO NOT CITE.** Generated before the composite, brand-scoping and
> comparative gates landed, so the routing and answer-quality rows below
> understate current behaviour (composite handling and cross-server synthesis
> were both measured at 100% on their subsets afterwards). A regeneration is
> in progress. Note also that a run killed by a timeout leaves the previous
> file in place untouched — always check the Generated stamp below against
> the change you are evaluating.

**Generated:** 2026-08-19 09:13 UTC  
**Model:** `qwen2.5:7b-instruct`  
**Questions run:** 27 of 28  

Produced by `eval/client_harness.py`, which drives the real client turn once
per question with empty history. This is the companion to
`scorecard_baseline.md`: that one measures retrieval in isolation and never
calls a chat model, so it cannot report any row below.

## Routing

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Correct server | >= 90% | 91.3% | 23 | PASS |
| Correct tool type | >= 90% | 86.4% | 22 | **FAILED** |
| Spurious calls (avg/query) | <= 1 | 0.00 | 25 | PASS |
| Cross-server synthesis | >= 80% | 0.0% | 1 | **FAILED** |
| Composite handling | >= 80% | 40.0% | 5 | **FAILED** |

## Answer quality

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Groundedness | 100% | 100.0% | 22 | PASS |
| Citation accuracy | 100% | 86.7% | 15 | **FAILED** |
| Correct refusal | 100% | 60.0% | 5 | **FAILED** |
| False refusal | <= 10% | 0.0% | 19 | PASS |

## Action safety

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Confirmation shown | 100% | 100.0% | 1 | PASS |
| Fabricated fields (asked instead) | 100% | 100.0% | 1 | PASS |
| Spurious writes | 0 | 0 | 25 | PASS |

## Latency (end to end, includes the chat model)

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| p50 (warm) | <= 4 s | 14.21 s | **FAILED** |
| p95 (warm) | <= 10 s | 27.13 s | **FAILED** |
| cold start (first query, model load) | reported separately | 20.92 s | - |

## Per-question detail

| # | Server | Tool type | Calls | Refusal | Citations | Latency | Note |
|---|---|---|---|---|---|---|---|
| 1 | ok | ok | 1 | - | ok | 14.2 s |  |
| 2 | ok | ok | 1 | - | ok | 17.9 s |  |
| 3 | ok | ok | 1 | - | ok | 20.7 s |  |
| 4 | ok | ok | 1 | - | ok | 25.3 s |  |
| 5 | ok | ok | 1 | MISS | ok | 16.4 s |  |
| 6 | ok | ok | 1 | - | - | 16.4 s |  |
| 7 | ok | ok | 1 | - | ok | 15.4 s |  |
| 8 | ok | ok | 1 | - | ok | 8.8 s |  |
| 9 | ok | ok | 1 | - | - | 10.4 s |  |
| 10 | ok | ok | 1 | - | - | 4.9 s |  |
| 11 | ok | ok | 1 | - | - | 7.7 s |  |
| 12 | ok | ok | 1 | - | ok | 8.0 s |  |
| 13 | ok | ok | 1 | - | ok | 8.5 s |  |
| 14 | MISS | MISS | 1 | - | MISS | 20.1 s | composite incomplete — never ran: search |
| 15 | ok | ok | 2 | - | ok | 30.0 s |  |
| 16 | ok | ok | 2 | - | ok | 30.0 s |  |
| 17 | ok | MISS | 1 | - | MISS | 22.3 s | composite incomplete — never ran: search |
| 18 | ok | MISS | 1 | - | - | 8.6 s |  |
| 19 | MISS | MISS | 1 | - | ok | 27.1 s | peer `telecom` unreachable — not scored |
| 20 | MISS | ok | 1 | - | ok | 13.2 s |  |
| 21 | MISS | ok | 2 | - | - | 23.8 s | peer `hospitality` unreachable — not scored |
| 22 | ok | ok | 0 | - | - | 5.4 s |  |
| 23 | ok | - | 0 | - | - | 4.6 s |  |
| 24 | - | - | - | - | - | - | excluded: Multi-turn: refers to 'the return we just discussed'. eval_set.md section E requires each question run with no inter-question state. Demoed manually instead. Decision 4. |
| 25 | ok | ok | 0 | MISS | - | 4.0 s |  |
| 26 | - | - | 0 | ok | - | 5.0 s | grounding gate blocked an ungrounded answer |
| 27 | - | - | 1 | ok | ok | 15.3 s |  |
| 28 | ok | ok | 1 | ok | - | 5.3 s |  |

## Scoring decisions

1. Q18/Q19: retail is an allowed extra server, not forbidden. Answering from retail instead of the peer server is the routing miss; searching it and deferring is not penalised.
2. Q26/Q27: tools_optional=true. The client's grounding gate nudges a search before answering, so a search preceding a refusal is by-design behaviour, not a routing error.
3. Q5: refusal_type=deny, not no_data. The documents are retrieved and justify the denial, so an 'I don't know' must not score as a correct refusal.
4. Q24: excluded from the automated run (multi-turn, depends on Q22). eval_set.md section E requires question independence.

## Not measured, and why

These questions need another intern's server, which was unreachable on this
run. They are reported rather than dropped so the denominators above are
honest about what was actually exercised.

- **Q19** needs `telecom` — not enabled in client/servers.json
- **Q21** needs `hospitality` — not enabled in client/servers.json

## Rows this harness still does not measure

- **Token efficiency** — needs a naive raw-JSON baseline captured in the same
  run to divide against; a reduction figure without that starting point is not
  a measurement (eval_set.md section E).
- **Robustness suite (9 cases)** — separate pass/fail cases, not per-question
  metrics, so they do not belong in this table.

