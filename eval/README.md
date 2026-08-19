# eval/

- `eval_set.md` — 28 questions + expected answers
- `ground_truth.json` — machine-readable form of the eval set (the harness reads this, not the markdown)
- `harness.py` — one-command baseline scorecard (retrieval only, no LLM)
- `client_harness.py` — the companion scorecard for everything `harness.py`
  structurally cannot measure: routing, answer quality, action safety and
  end-to-end latency. Drives the real client turn, so it needs a running MCP
  server and chat model. Writes `scorecard_client.md`.
- `scorecard_baseline.md` — latest baseline scorecard output
