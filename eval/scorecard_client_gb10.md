# Scorecard — client layer (routing, answer quality, latency)

**Generated:** 2026-08-27 11:45 UTC  
**Model:** `topaz-coder`  
**Questions run:** 27 of 28  

Produced by `eval/client_harness.py`, which drives the real client turn once
per question with empty history. This is the companion to
`scorecard_baseline.md`: that one measures retrieval in isolation and never
calls a chat model, so it cannot report any row below.

## Routing

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Correct server | >= 90% | 95.5% | 22 | PASS |
| Correct tool type | >= 90% | 90.9% | 22 | PASS |
| Spurious calls (avg/query) | <= 1 | 0.12 | 25 | PASS |
| Cross-server synthesis | >= 80% | 100.0% | 1 | PASS |
| Composite handling | >= 80% | 80.0% | 5 | PASS |

## Answer quality

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Groundedness | 100% | 100.0% | 22 | PASS |
| Citation accuracy | 100% | 100.0% | 14 | PASS |
| Correct refusal | 100% | 80.0% | 5 | **FAILED** |
| False refusal | <= 10% | 5.3% | 19 | PASS |

## Action safety

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Confirmation shown | 100% | 100.0% | 1 | PASS |
| Fabricated fields (asked instead) | 100% | 100.0% | 1 | PASS |
| Spurious writes | 0 | 0 | 25 | PASS |

## Latency (end to end, includes the chat model)

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| p50 (warm) | <= 4 s | 2.66 s | PASS |
| p95 (warm) | <= 10 s | 7.31 s | PASS |
| cold start (first query, model load) | reported separately | 7.76 s | - |

## Per-question detail

| # | Server | Tool type | Calls | Refusal | Citations | Latency | Note |
|---|---|---|---|---|---|---|---|
| 1 | ok | MISS | 1 | - | - | 2.3 s |  |
| 2 | ok | ok | 1 | - | ok | 3.2 s |  |
| 3 | ok | ok | 1 | - | ok | 3.6 s |  |
| 4 | ok | ok | 1 | - | ok | 3.4 s |  |
| 5 | ok | ok | 1 | ok | - | 3.0 s |  |
| 6 | ok | ok | 2 | - | - | 4.6 s |  |
| 7 | ok | ok | 1 | - | ok | 2.8 s |  |
| 8 | ok | ok | 1 | - | ok | 3.3 s |  |
| 9 | ok | ok | 1 | - | ok | 2.7 s |  |
| 10 | ok | ok | 1 | - | ok | 1.7 s |  |
| 11 | ok | ok | 1 | - | ok | 2.4 s |  |
| 12 | ok | ok | 1 | - | ok | 1.5 s |  |
| 13 | ok | ok | 1 | - | ok | 1.9 s |  |
| 14 | ok | ok | 3 | - | - | 7.3 s |  |
| 15 | ok | ok | 2 | - | ok | 4.0 s |  |
| 16 | ok | ok | 2 | - | ok | 9.6 s |  |
| 17 | ok | ok | 2 | - | - | 5.1 s |  |
| 18 | MISS | MISS | 0 | MISS | - | 1.7 s | grounding gate blocked an ungrounded answer |
| 19 | MISS | MISS | 0 | MISS | - | 1.6 s | peer `telecom` unreachable — not scored |
| 20 | ok | ok | 2 | - | ok | 12.3 s |  |
| 21 | MISS | ok | 1 | - | ok | 6.2 s | peer `hospitality` unreachable — not scored |
| 22 | ok | ok | 0 | - | - | 1.4 s |  |
| 23 | - | - | 0 | - | - | 0.2 s |  |
| 24 | - | - | - | - | - | - | excluded: Multi-turn: refers to 'the return we just discussed'. eval_set.md section E requires each question run with no inter-question state. Demoed manually instead. Decision 4. |
| 25 | ok | ok | 0 | MISS | - | 1.4 s |  |
| 26 | - | - | 0 | ok | - | 1.8 s | grounding gate blocked an ungrounded answer |
| 27 | - | - | 0 | ok | - | 2.6 s | grounding gate blocked an ungrounded answer |
| 28 | ok | ok | 1 | ok | ok | 2.0 s |  |

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

