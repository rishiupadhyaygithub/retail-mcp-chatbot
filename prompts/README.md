# prompts/

Versioned system prompt(s) for the client LLM. Bump the version on any change.

- `system_prompt_v1.md` — active. Loaded by `client/loop.py`; only the text
  below the `---` fence is sent to the model.

**Do not edit a version in place once a scorecard has been generated against
it.** Each scorecard records the prompt version, and a silently edited v1 makes
two runs incomparable. Phase 2 (records) becomes v2, phase 3 (actions) v3.

The prompt is not the whole grounding story. Measured behaviour showed the
model answering without retrieving and citing documents it had never seen, so
the hard guarantee lives in `client/loop.py` as a gate. See `client/README.md`.
