# Evaluation Set & Scorecard — Retail / E-commerce

**Author:** Rishi — Intern 3 (Retail)
**Purpose:** 25–30 hand-written questions with expected behaviour, + the scorecard the harness produces. Baseline-gate deliverable — exists **before** the chatbot does.

> **Corpus sources are now pinned** — the 22 documents exist, so every document-grounded question below names its expected files. **[TODO]** now means dataset-only: the reference customer IDs in §B, which cannot be filled until the phase-2 SQLite data is generated.

---

## A. Corpus plan (phase 1) — source your own, 15–40 docs

- **Majority real public documentation.** Retailers publish extensive help centres, returns/refund/warranty/delivery terms. Public pages only. Sources listed in `data/sources.md`.
- **Four companies — Amazon, Best Buy, IKEA, Target** — chosen for differing terminology for the same thing + genuinely conflicting policies, the mess the system must handle. Source URLs in `data/sources.md`.
- **Deliberately contradicting pair: Amazon ~30-day standard returns vs Best Buy 15-day (14-day cellular; $45 restocking fee on activatable devices).** Bonus spread: IKEA 365-day, Target 90-day. The system must surface the conflict, not blend them. All 22 corpus docs are **real public pages** (no LLM-generated filler); their natural inconsistency in terms and coverage is the mess the system must handle.
- **Mix long and short docs** — uniform length hides chunking problems.

## B. Dataset plan (phase 2) — generate it, synthetic

- ~4–6 SQLite tables: `orders`, `line_items`, `shipments`, `returns`, `customers`. A few hundred to a few thousand rows.
- **Consistent with the documents** — if a policy doc says refunds take 5 working days, the data shows ~5, with a few exceptions (exceptions are what agents call about).
- **Awkward cases included:** a duplicate charge, a partially shipped order, a return already under review, a customer with two accounts.
- **3–4 reference customers** documented with their IDs for demos. **[TODO: pin IDs once generated.]**
- Small enough to inspect by hand — I must know the right answer to score my own eval.

---

## C. Questions

Phrased the way an agent asks mid-call. Each records what *should* happen.

> **This file is the human-readable form. `eval/ground_truth.json` is the machine-readable form the harness actually reads** — it holds the same expected document sets plus the quoted passage that justifies each one. The two must be kept in sync: change a question or an expected source here, change it there in the same commit, or the scorecard stops describing this document. All paths below are relative to `data/corpus/`.
>
> **11 of the 28 questions are scoreable at the baseline gate** — the 7 Document questions and the document half of the 4 Composite ones. Record, Cross-server, Action and Unanswerable questions need phase 2/3 or another intern's server, so they carry no expected corpus path yet. At 11 questions each miss costs 9.09 points, so the ≥85% Recall@5 gate allows exactly one miss (10/11 = 90.9%; 9/11 = 81.8% fails).

### Document (7) — incl. two-document answers + vocabulary differing from source

| # | Question (agent voice) | Should do | Expected |
|---|------------------------|-----------|----------|
| 1 | "how long till they get their money back on a return?" | search | refund-window passage; note "money back" must match a "refund" chunk (vocab differs) — `amazon/refund_timelines.md`, `target/returns.md`, `bestbuy/returns.md` |
| 2 | "customer's parcel never showed up — what's our process?" | search | delivery-failure passage — `amazon/order_tracking.md`, `bestbuy/order_tracking.md` |
| 3 | "can they send back opened electronics?" | search | returns-eligibility passage — `bestbuy/returns.md`, `target/returns.md`, `amazon/returns.md` |
| 4 | "what's covered under warranty and for how long?" | search | warranty passage stating **both** scope and term — `ikea/warranty_terms.md`, `amazon/warranty.md`, `ikea/warranty.md` |
| 5 | "they want to return after 40 days, are we allowed?" | search → **refuse/deny** | return-window passage; answer = no — `amazon/returns.md` (30d), `bestbuy/returns.md` (15d) |
| 6 | "returns window AND who pays return shipping?" | search (**two documents**) | returns-policy + shipping-cost docs — `amazon/returns.md`, `target/returns.md`, `bestbuy/returns.md`, `bestbuy/delivery.md` |
| 7 | "does every store charge a 'restocking fee' on returns?" | search (**vocab conflict across docs**) | Best Buy $45 activatable-device fee vs IKEA / Target (no such fee) — flag they differ — `bestbuy/returns.md`, `ikea/returns.md`, `target/returns.md` |

**Deliberate exclusions in the expected sets above** (recorded so the harness is not "fixed" later by quietly widening them):

- **Q5 lists only the two windows shorter than 40 days.** `target/returns.md` (90 days) and `ikea/returns.md` (365 / 180 days) are excluded on purpose — retrieving them grounds a *yes*, and the expected behaviour here is a refusal. This is the strictest item in the set and the likeliest first Recall@1 failure; if it fails, the honest move is the accept-set argument under design doc §7, not a wider list.
- **Q1 and Q17 exclude `ikea/returns.md`** — it gives the refund *method* ("same form of payment originally used") but no timing, so it cannot answer "how long".
- **Q4 excludes `bestbuy/warranty.md` and `target/warranty.md`** — both describe coverage but publish no term length, so they fail the "for how long" half.
- **Q3 excludes `ikea/returns.md`** — its "Open products: 180 days" covers opened goods, but IKEA sells no electronics.

### Record (6) — exact lookups, filtered lists, ≥1 aggregate

| # | Question | Should do | Expected |
|---|----------|-----------|----------|
| 8 | "status of order [REF]?" | query_orders | that order's status |
| 9 | "did order [REF] actually ship?" | query_shipments | shipment row |
| 10 | "list this customer's open returns" | query_returns (filtered) | filtered list |
| 11 | "how many orders has [customer] placed this year?" | query (**aggregate/count**) | correct count |
| 12 | "**how much has this customer been refunded this year?**" | query (**aggregate/sum**) | correct total |
| 13 | "which line items in order [REF] were delivered?" | query_line_items (filtered) | filtered rows |

### Composite (4) — need documents AND records in one answer

| # | Question | Should do | Expected |
|---|----------|-----------|----------|
| 14 | "**I was charged twice — is that allowed and did it actually happen?**" | search (payments policy) + query (duplicate charge) | policy + the duplicate-charge row; document half = `amazon/charged_twice.md` |
| 15 | "can they return order [REF] — what's the window and is it eligible?" | query_orders + search (returns policy) | order date + policy → eligible/not; document half = `amazon/returns.md`, `bestbuy/returns.md`, `target/returns.md`, `ikea/returns.md` |
| 16 | "parcel split into two — is partial delivery covered, and what shipped?" | search (delivery policy) + query_shipments | policy + partial-shipment rows; document half = `amazon/charged_twice.md`, `amazon/delivery.md` |
| 17 | "refund on [REF] — how long should it take and did it go through?" | search + query_returns | policy window + return status; document half = `amazon/refund_timelines.md`, `target/returns.md`, `bestbuy/returns.md` |

**Only the document half of Q14–Q17 is scored at the baseline gate**; the record half waits for phase 2. Three corpus gaps found while pinning these, worth quoting in the scorecard commentary rather than papering over:

1. **Q16 has no dedicated partial-delivery document.** The only explicit split-shipment language in the corpus sits inside `amazon/charged_twice.md`, which is typed `payments` — so a correct retrieval for a *delivery* question has to surface a payments chunk. Expect this to look like a routing failure when it is really a corpus gap.
2. **Q6's "who pays return shipping" half is only weakly covered.** The corpus says prepaid/printable return labels exist (Amazon, Target) but no document states outright who bears the cost. `bestbuy/delivery.md` is included as the nearest genuine shipping-cost passage ($35 free-shipping threshold), though it covers outbound, not return, shipping.
3. **Q14 has a single-point-of-failure expected set** — one document, so Recall@5 on Q14 is effectively a test of one chunk. Related: there is no `amazon/payments.md` at all; Amazon's payments coverage is two special-case documents. No question in this set asks "what payment methods does Amazon accept?", and none should until the gap is filled — it would score as a retrieval miss when the honest answer is missing corpus.

### Cross-server (4) — ≥2 need another industry, ≥1 comparative across two at once

| # | Question | Should do | Expected |
|---|----------|-----------|----------|
| 18 | "does the **bank** show a refund for this charge yet?" | route → **Banking** server | banking record; not retail |
| 19 | "customer disputing a **telecom** bill, not our order" | route → **Telecom** server | telecom; retail refuses its part |
| 20 | "**do refund timelines differ between us and the bank?**" | **comparative — retail + Banking at once** | both policies, compared |
| 21 | "compare our return window with the **hotel's** cancellation window" | **comparative — retail + Hospitality** | both, compared |

### Action (4) — incl. one missing-field → client must ask

| # | Question | Should do | Expected |
|---|----------|-----------|----------|
| 22 | "open a return for order [REF], item [ITEM], reason damaged" | `kb_retail_create_return`, **confirm first** | confirmation showing fields, then RMA ref |
| 23 | "start a return for this customer" (**missing order/item**) | **client asks for the missing fields**, does not invent | prompts for order_id + line_item_id |
| 24 | "raise the return we just discussed" (follow-up, multi-turn) | `kb_retail_create_return` using prior turn's order, confirm | RMA ref |
| 25 | "open a return on order [REF]" but item already returned | `kb_retail_create_return` → error (`retryable: false`) | loud fail, no silent default |

### Unanswerable (3) — retrieval should fail, system should refuse

| # | Question | Should do | Expected |
|---|----------|-----------|----------|
| 26 | "what's the CEO's mobile number?" | **refuse** | not in data |
| 27 | "will this product be cheaper next month?" | **refuse** | can't predict |
| 28 | "status of order 99999999?" (**no such order**) | query → empty → **refuse honestly** | zero rows, not invented |

*(28 questions — inside 25–30.)*

---

## D. Scorecard — reported TWICE (baseline when retrieval works, final after tuning)

Each layer measured separately.

**Retrieval (phase 1):** Recall@5 ≥85% · Recall@1 ≥60% *(may argue accept-set on Recall@1 if my corpus has genuine policy conflicts — see design doc §7)*

**Routing:** correct server ≥90% · correct tool-type ≥90% · spurious calls ≤1/query avg · cross-server synthesis ≥80% · composite handling ≥80%

**Structured (phase 2):** query correctness ≥90% · numerical accuracy 100% · empty-result honesty 100%

**Answer quality:** groundedness 100% · citation accuracy 100% · correct refusal 100% · false refusal ≤10%

**Action safety (phase 3):** spurious writes 0 · fabricated fields 0 · correct action routing 100% · confirmation shown 100%

**Latency:** e2e p50 ≤4s · p95 ≤10s · retrieval ≤300ms · query ≤100ms · MCP overhead ≤100ms · *(warm vs cold reported separately — Ollama unloads idle models)*

**Token efficiency:** tokens/query reported → reduced ≥40% vs naive raw-JSON injection · no groundedness/recall regression

**Robustness (pass/fail, none may crash):** 1 server down · all servers down · empty query · 5000-word query · wrong-language query · off-topic question · 10000-row match · missing customer ref · two identical concurrent requests

---

## E. Measurement harness (`eval/run_evals.py`)

One script, one command, prints the scorecard as one table.

- Reads `eval/ground_truth.json` (question + expected sources) — the machine-readable twin of §C, not this markdown.
- Runs **each question in a fresh session** (else a question passes only because an earlier turn retrieved the right passage → numbers stop being repeatable).
- Scores each layer separately; logs per query which servers/tools were called, what they returned, latency per stage.
- **Instruments token counts from the baseline run onward** — a reduction figure with no starting point is not a measurement.
- Runs the token test **both ways** (verbose vs compact) and reports both numbers.

_(Harness code lands at the baseline gate, with the first scorecard.)_
