# Scorecard — client layer (routing, answer quality, latency)

**Generated:** 2026-08-19 11:59 UTC  
**Model:** `qwen2.5:7b-instruct`  
**Questions run:** 27 of 28  

Produced by `eval/client_harness.py`, which drives the real client turn once
per question with empty history. This is the companion to
`scorecard_baseline.md`: that one measures retrieval in isolation and never
calls a chat model, so it cannot report any row below.

## Routing

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Correct server | >= 90% | 85.0% | 20 | **FAILED** |
| Correct tool type | >= 90% | 85.0% | 20 | **FAILED** |
| Spurious calls (avg/query) | <= 1 | 0.00 | 23 | PASS |
| Cross-server synthesis | >= 80% | n/a | 0 | not measured |
| Composite handling | >= 80% | 100.0% | 4 | PASS |

## Answer quality

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Groundedness | 100% | 85.0% | 20 | **FAILED** |
| Citation accuracy | 100% | 100.0% | 15 | PASS |
| Correct refusal | 100% | 20.0% | 5 | **FAILED** |
| False refusal | <= 10% | 0.0% | 17 | PASS |

## Action safety

| Metric | Target | Measured | n | Verdict |
|---|---|---|---|---|
| Confirmation shown | 100% | 0.0% | 1 | **FAILED** |
| Fabricated fields (asked instead) | 100% | 0.0% | 1 | **FAILED** |
| Spurious writes | 0 | 0 | 23 | PASS |

## Latency (end to end, includes the chat model)

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| p50 (warm) | <= 4 s | 75.41 s | **FAILED** |
| p95 (warm) | <= 10 s | 182.28 s | **FAILED** |
| cold start (first query, model load) | reported separately | 109.74 s | - |

## Per-question detail

| # | Server | Tool type | Calls | Refusal | Citations | Latency | Note |
|---|---|---|---|---|---|---|---|
| 1 | ok | ok | 1 | - | ok | 60.8 s |  |
| 2 | ok | ok | 1 | - | ok | 66.3 s |  |
| 3 | ok | ok | 1 | - | ok | 105.6 s |  |
| 4 | ok | ok | 1 | - | ok | 81.3 s |  |
| 5 | ok | ok | 1 | ok | ok | 66.3 s |  |
| 6 | ok | ok | 1 | - | ok | 63.5 s |  |
| 7 | ok | ok | 1 | - | ok | 101.0 s |  |
| 8 | ok | ok | 1 | - | ok | 223.9 s |  |
| 9 | ok | ok | 1 | - | ok | 104.1 s |  |
| 10 | ok | ok | 1 | - | - | 75.4 s |  |
| 11 | ok | ok | 1 | - | ok | 182.3 s |  |
| 12 | ok | ok | 1 | - | ok | 248.2 s |  |
| 13 | ok | ok | 1 | - | - | 94.3 s |  |
| 14 | ok | ok | 2 | - | ok | 117.9 s |  |
| 15 | ok | ok | 2 | - | ok | 142.1 s |  |
| 16 | ok | ok | 2 | - | ok | 101.4 s |  |
| 17 | ok | ok | 2 | - | ok | 168.2 s |  |
| 18 | MISS | MISS | 1 | MISS | - | 53.2 s | peer `banking` unreachable — not scored |
| 19 | MISS | MISS | 0 | MISS | - | 39.1 s | peer `telecom` unreachable — not scored |
| 20 | MISS | ok | 1 | - | ok | 72.7 s | peer `banking` unreachable — not scored |
| 21 | MISS | ok | 1 | - | ok | 140.1 s | peer `hospitality` unreachable — not scored |
| 22 | MISS | MISS | 0 | - | - | 30.4 s |  |
| 23 | - | - | 0 | - | - | 30.1 s |  |
| 24 | - | - | - | - | - | - | excluded: Multi-turn: refers to 'the return we just discussed'. eval_set.md section E requires each question run with no inter-question state. Demoed manually instead. Decision 4. |
| 25 | MISS | MISS | 0 | MISS | - | 30.1 s |  |
| 26 | - | - | 0 | MISS | - | 30.0 s |  |
| 27 | - | - | 0 | MISS | - | 30.0 s |  |
| 28 | MISS | MISS | 0 | MISS | - | 30.0 s |  |

## Scoring decisions

1. Q18/Q19: retail is an allowed extra server, not forbidden. Answering from retail instead of the peer server is the routing miss; searching it and deferring is not penalised.
2. Q26/Q27: tools_optional=true. The client's grounding gate nudges a search before answering, so a search preceding a refusal is by-design behaviour, not a routing error.
3. Q5: refusal_type=deny, not no_data. The documents are retrieved and justify the denial, so an 'I don't know' must not score as a correct refusal.
4. Q24: excluded from the automated run (multi-turn, depends on Q22). eval_set.md section E requires question independence.

## Not measured, and why

These questions need another intern's server, which was unreachable on this
run. They are reported rather than dropped so the denominators above are
honest about what was actually exercised.

- **Q18** needs `banking` — no response within 30s
- **Q19** needs `telecom` — not enabled in client/servers.json
- **Q20** needs `banking` — no response within 30s
- **Q21** needs `hospitality` — not enabled in client/servers.json

## Rows this harness still does not measure

- **Token efficiency** — needs a naive raw-JSON baseline captured in the same
  run to divide against; a reduction figure without that starting point is not
  a measurement (eval_set.md section E).
- **Robustness suite (9 cases)** — separate pass/fail cases, not per-question
  metrics, so they do not belong in this table.

