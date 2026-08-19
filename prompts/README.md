# prompts/

Versioned system prompt(s) for the client LLM. Bump the version on any change.

- `system_prompt_v2.md` — **active**. Loaded by `client/loop.py`; only the text
  below the `---` fence is sent to the model. v2 adds the record-tool rules and
  history isolation that phase 2 needed.
- `system_prompt_v1.md` — superseded, kept because `scorecard_baseline.md` was
  generated against it and deleting it would orphan that scorecard.

**Do not edit a version in place once a scorecard has been generated against
it.** Each scorecard records the prompt version, and a silently edited version
makes two runs incomparable. Phase 3 (actions) becomes v3.

The prompt is not the whole grounding story, and this is the central lesson of
the client so far: **wording cannot make a guarantee, only code can.** Three
separate failures were measured and none was fixable by editing this file.

- The model answered without retrieving and cited documents it had never seen.
- It answered composite questions from one half and stated them as complete.
- Asked once to search before answering, it answered anyway and cited a
  document that does not exist in the corpus.

Each is now a gate in `client/loop.py` that either fetches the missing evidence
itself or refuses to show the answer. The prompt states the intent; the gates
enforce it. See `client/README.md`.
