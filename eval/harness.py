#!/usr/bin/env python3
"""Baseline measurement harness for the retail MCP knowledge assistant. One command, one table.

Reads the ground truth from eval/ground_truth.json, embeds each question LOCALLY with the same model
the server will use (BAAI/bge-m3), queries the Chroma collection(s) built by ingestion, and
prints a markdown scorecard to stdout (also written to --out). Progress goes to stderr. This file NEVER
calls a chat LLM: retrieval is measured here, reasoning belongs in the client.

    python3 eval/harness.py                     # both strategies, top_k=5, scorecard to eval/scorecard_baseline.md
    python3 eval/harness.py --strategy packed --top-k 10
Exit codes: 0 = the harness ran and produced a scorecard (targets may still have FAILED; the code reports
whether the measurement ran, not whether it passed). 1 = bad input (unusable ground truth, missing corpus
file, missing dependency). 2 = argparse usage error. 3 = a required Chroma collection is missing or empty,
so ingestion has to run first.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

# Paths resolved from this file's own location. No hardcoded absolutes.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CORPUS_ROOT = REPO_ROOT / "data" / "corpus"
DEFAULT_GROUND_TRUTH = REPO_ROOT / "eval" / "ground_truth.json"
DEFAULT_OUT = REPO_ROOT / "eval" / "scorecard_baseline.md"
DEFAULT_DB = REPO_ROOT / "data" / "chroma"
EMBED_MODEL = "BAAI/bge-m3"
COLLECTIONS = {"heading": "retail_docs", "packed": "retail_docs_packed"}
SOURCE_KEYS = ("relative_path", "path", "source_path", "file", "source")
INGEST_HINT = ("Run ingestion first:\n         python3 data/ingest.py --strategy heading\n"
               "         python3 data/ingest.py --strategy packed")
EXIT_OK, EXIT_BAD_INPUT, EXIT_NO_COLLECTION = 0, 1, 3  # 2 is reserved: argparse uses it for usage errors
NA_CLIENT, NA_P3 = "n/a - needs client", "n/a - needs phase 3"
# Rows that cannot be measured yet. They stay in the table on purpose: omitting them would
# misrepresent how much of the brief's scorecard this baseline actually covers.
NA_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Routing: correct server", "client router, not built", ">= 90%", NA_CLIENT),
    ("Routing: correct tool type", "client router, not built", ">= 90%", NA_CLIENT),
    ("Routing: spurious calls", "client tool-call loop, not built", "<= 1/query", NA_CLIENT),
    ("Routing: cross-server synthesis", "needs 2+ interns' servers", ">= 80%", NA_CLIENT),
    ("Routing: composite handling", "needs documents + records in one answer", ">= 80%", NA_CLIENT),
    ("Answer quality: groundedness", "needs generated answers", "100%", NA_CLIENT),
    ("Answer quality: citation accuracy", "needs generated answers", "100%", NA_CLIENT),
    ("Answer quality: correct refusal", "needs generated answers (Q5, Q26-28)", "100%", NA_CLIENT),
    ("Answer quality: false refusal", "needs generated answers", "<= 10%", NA_CLIENT),
    ("Action safety: spurious writes", "phase-3 write tools not built", "0", NA_P3),
    ("Action safety: fabricated fields", "phase-3 write tools not built", "0", NA_P3),
    ("Action safety: correct action routing", "phase-3 write tools not built", "100%", NA_P3),
    ("Action safety: confirmation shown", "phase-3 write tools not built", "100%", NA_P3),
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def die(code: int, msg: str) -> Any:
    print(f"\nERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def rel(p: Path) -> str:
    """Repo-relative display path, falling back to the absolute one."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


# --- Ground truth: data, not code. The eval set is a hand-edited deliverable. ---
def known_corpus_docs() -> set[str]:
    if not CORPUS_ROOT.is_dir():
        die(EXIT_BAD_INPUT, f"corpus directory not found: {CORPUS_ROOT}")
    docs = {f"{p.parent.name}/{p.name}" for p in CORPUS_ROOT.glob("*/*.md")}
    return docs or die(EXIT_BAD_INPUT, f"no *.md documents found under {CORPUS_ROOT}")


def normalise_doc_id(raw: Any) -> str | None:
    """Reduce any path-ish document identifier to '<brand>/<file>.md'. Returns None when the value
    cannot be read as a corpus path; the caller decides how loudly to fail, and an unrecognised
    value is always reported rather than quietly scored as a miss."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    parts = [p for p in raw.strip().replace("\\", "/").split("/") if p and p != "."]
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def load_ground_truth(path: Path, corpus: set[str]) -> list[dict[str, Any]]:
    if not path.is_file():
        die(EXIT_BAD_INPUT, f"ground truth not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(EXIT_BAD_INPUT, f"{path} is not valid JSON: {exc}")
    # Accepts 1 and 2.  Schema 2 only ADDS keys (`routing_labels`,
    # `label_meanings`, `scoring_decisions`) for the client harness; every field
    # this harness reads is unchanged, so refusing to run against it would fail
    # on a compatible file.  Bump this list deliberately when a schema actually
    # changes a field this file depends on.
    if not isinstance(data, dict) or data.get("schema_version") not in (1, 2):
        die(EXIT_BAD_INPUT,
            f"{path}: expected an object with schema_version in (1, 2), "
            f"got {data.get('schema_version') if isinstance(data, dict) else type(data).__name__}")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        die(EXIT_BAD_INPUT, f"{path}: 'questions' must be a non-empty list")
    seen: set[int] = set()
    for i, q in enumerate(questions):
        where = f"{path}: questions[{i}]"
        if not isinstance(q, dict):
            die(EXIT_BAD_INPUT, f"{where} is not an object")
        num, text, expected = q.get("number"), q.get("question"), q.get("expected_docs")
        if not isinstance(num, int) or num in seen:
            die(EXIT_BAD_INPUT, f"{where}: 'number' must be a unique integer (got {num!r})")
        seen.add(num)
        if not isinstance(text, str) or not text.strip():
            die(EXIT_BAD_INPUT, f"{where}: 'question' must be a non-empty string")
        if not isinstance(expected, list) or not expected:
            die(EXIT_BAD_INPUT, f"{where}: 'expected_docs' must be a non-empty list")
        q["expected_docs"] = [normalise_doc_id(d) for d in expected]
        for original, norm in zip(expected, q["expected_docs"]):
            if norm is None or norm not in corpus:
                die(EXIT_BAD_INPUT, f"{where}: expected_doc {original!r} does not exist under {CORPUS_ROOT}. Fix "
                                    f"the ground truth or the corpus - the harness will not score against a "
                                    f"document that is not there.")
    declared = data.get("scoreable_count")
    if isinstance(declared, int) and declared != len(questions):
        die(EXIT_BAD_INPUT, f"{path}: scoreable_count says {declared} but 'questions' holds {len(questions)}. "
                            f"n must be unambiguous.")
    return sorted(questions, key=lambda q: q["number"])


@dataclass
class RecordEvaluationItem:
    number: int
    question: str
    tool: str
    arguments: dict[str, Any]
    passed: bool
    latency_ms: float
    details: str


@dataclass
class RecordScoreResult:
    items: list[RecordEvaluationItem]
    passed_count: int
    total_count: int
    numerical_accuracy_passed: bool
    empty_result_honesty_passed: bool
    p50_ms: float
    p95_ms: float

    @property
    def accuracy_pct(self) -> float:
        return (self.passed_count / self.total_count * 100.0) if self.total_count else 0.0


def evaluate_records(gt_path: Path) -> RecordScoreResult:
    from server.records import RetailRecords
    data = json.loads(gt_path.read_text(encoding="utf-8"))
    record_questions = data.get("record_questions", [])
    records = RetailRecords()

    items: list[RecordEvaluationItem] = []
    latencies: list[float] = []

    for q in record_questions:
        num = q["number"]
        question_text = q["question"]
        tool_name = q["tool"]
        args = q["arguments"]
        exp = q.get("expected_record", {})

        t0 = time.perf_counter()
        if tool_name == "kb_retail_query_orders":
            res = records.query_orders(**args)
        elif tool_name == "kb_retail_query_shipments":
            res = records.query_shipments(**args)
        elif tool_name == "kb_retail_query_returns":
            res = records.query_returns(**args)
        elif tool_name == "kb_retail_query_customer":
            res = records.query_customer(**args)
        else:
            res = {"results": [], "total_found": 0, "error": "unknown tool"}
        lat_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat_ms)

        passed = True
        details = "matched"

        if num == 8:
            if not (res.get("total_found") == 1 and res["results"][0]["order_id"] == exp["order_id"] and res["results"][0]["status"] == exp["status"]):
                passed = False
                details = f"Expected order {exp['order_id']} ({exp['status']}), got {res.get('results')}"
        elif num == 9:
            shipments = res.get("results", [])
            if len(shipments) != 2 or not {"delivered", "in_transit"}.issubset({s["status"] for s in shipments}):
                passed = False
                details = f"Expected 2 shipments (delivered, in_transit), got {len(shipments)}"
        elif num == 10:
            rets = res.get("results", [])
            if len(rets) != 1 or rets[0]["return_id"] != "RET-701" or rets[0]["status"] != "refund_processing":
                passed = False
                details = f"Expected RET-701 in refund_processing, got {rets}"
        elif num == 11:
            custs = res.get("results", [])
            if not (custs and custs[0]["aggregates_2026"]["orders_placed_count"] == exp["orders_placed_count"]):
                passed = False
                details = f"Expected {exp['orders_placed_count']} orders, got {custs}"
        elif num == 12:
            custs = res.get("results", [])
            if not (custs and custs[0]["aggregates_2026"]["total_refunded_completed"] == exp["total_refunded_completed"]):
                passed = False
                details = f"Expected total_refunded={exp['total_refunded_completed']}, got {custs}"
        elif num == 13:
            delivered = [item["line_item_id"] for s in res.get("results", []) if s["status"] == "delivered" for item in s.get("items", [])]
            if "ITEM-9021-1" not in delivered:
                passed = False
                details = f"Expected ITEM-9021-1 in delivered, got {delivered}"
        elif num == 14:
            orders = res.get("results", [])
            captured = [o for o in orders if o["payment_status"] == "captured"]
            authorized = [o for o in orders if o["payment_status"] == "authorized"]
            if not (len(captured) == 1 and len(authorized) == 1 and captured[0]["total_amount"] == 129.99):
                passed = False
                details = f"Expected 1 captured ($129.99) and 1 auth hold ($129.99), got {orders}"
        elif num == 15:
            orders = res.get("results", [])
            if not (orders and orders[0]["order_date"] == "2026-08-06" and orders[0]["brand"] == "amazon"):
                passed = False
                details = f"Expected Amazon order on 2026-08-06, got {orders}"
        elif num == 16:
            if res.get("total_found") != 2:
                passed = False
                details = f"Expected 2 packages, got {res.get('total_found')}"
        elif num == 17:
            rets = res.get("results", [])
            if not (rets and rets[0]["status"] == "refund_processing" and rets[0]["refund_date"] is None):
                passed = False
                details = f"Expected refund_processing with null refund_date, got {rets}"
        elif num == 28:
            if not (res.get("total_found") == 0 and res.get("results") == []):
                passed = False
                details = f"Expected empty result total_found=0, got {res}"

        items.append(
            RecordEvaluationItem(
                number=num,
                question=question_text,
                tool=tool_name,
                arguments=args,
                passed=passed,
                latency_ms=lat_ms,
                details=details,
            )
        )

    passed_count = sum(1 for item in items if item.passed)
    num_passed = all(item.passed for item in items if item.number in (11, 12, 14))
    empty_honesty_passed = any(item.number == 28 and item.passed for item in items)

    return RecordScoreResult(
        items=items,
        passed_count=passed_count,
        total_count=len(items),
        numerical_accuracy_passed=num_passed,
        empty_result_honesty_passed=empty_honesty_passed,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
    )


# --- Token counting for the naive baseline ---
@dataclass
class TokenCounter:
    label: str
    count: Callable[[str], int]


def build_token_counter(choice: str, st_model: Any) -> TokenCounter:
    """Pick a tokenizer. Whichever is used is NAMED in the scorecard - a token baseline is meaningless
    without knowing how it was counted. `tiktoken` is the GPT-family proxy and needs its encoding file;
    `hf` is the embedder's own WordPiece vocab, already on disk, so it always works offline."""

    def try_tiktoken() -> TokenCounter | None:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            enc.encode("warmup")
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            log(f"  tokenizer: tiktoken unusable ({type(exc).__name__}: {exc})")
            return None
        return TokenCounter("tiktoken cl100k_base (GPT-family proxy)", lambda s: len(enc.encode(s)))

    def try_hf() -> TokenCounter | None:
        try:
            tok = st_model.tokenizer
            tok("warmup", add_special_tokens=False, truncation=False)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            log(f"  tokenizer: bge tokenizer unusable ({type(exc).__name__}: {exc})")
            return None
        return TokenCounter(f"{EMBED_MODEL} SentencePiece (the embedder's own tokenizer)",
                            lambda s: len(tok(s, add_special_tokens=False, truncation=False)["input_ids"]))

    if choice == "tiktoken":
        return try_tiktoken() or die(EXIT_BAD_INPUT, "--tokenizer tiktoken requested but unusable")
    if choice == "hf":
        return try_hf() or die(EXIT_BAD_INPUT, "--tokenizer hf requested but unusable")
    counter = try_tiktoken() or try_hf() or die(EXIT_BAD_INPUT, "no usable tokenizer; the token baseline "
                                                                "cannot be measured")
    log(f"  tokenizer: using {counter.label}")
    return counter


# --- Measurement ---
@dataclass
class QResult:
    number: int
    question: str
    expected: list[str]
    retrieved: list[str]
    hit_at_1: bool
    hit_at_k: bool
    embed_ms: float
    search_ms: float
    tokens: int
    tokens_verbose: int  # indented JSON: the worst-case naive baseline

    @property
    def total_ms(self) -> float:
        return self.embed_ms + self.search_ms


@dataclass
class StrategyResult:
    name: str
    collection: str
    chunk_count: int
    results: list[QResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def cold(self) -> QResult:
        """The first query after model load. Reported on its own line, never in the warm stats."""
        return self.results[0]

    @property
    def warm(self) -> list[QResult]:
        return self.results[1:]

    @property
    def mean_tokens(self) -> float:
        return sum(r.tokens for r in self.results) / self.n

    @property
    def mean_tokens_verbose(self) -> float:
        return sum(r.tokens_verbose for r in self.results) / self.n

    def p95_latency(self) -> float:
        """Warm p95 retrieval latency in ms."""
        return percentile([r.total_ms for r in self.warm], 95.0) if self.warm else 0.0

    def passes_latency(self) -> bool:
        return self.p95_latency() <= 300.0

    def recall(self, at_1: bool = False) -> float:
        return 100.0 * sum(r.hit_at_1 if at_1 else r.hit_at_k for r in self.results) / self.n

    def cell(self, at_1: bool = False) -> str:
        hits = sum(r.hit_at_1 if at_1 else r.hit_at_k for r in self.results)
        return f"{self.recall(at_1):.1f}% ({hits}/{self.n})"


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile, stated explicitly so the reader knows what p95 means over a
    ten-sample warm set (it is the maximum observed)."""
    if not values:
        die(EXIT_BAD_INPUT, "percentile over an empty sample")
    ordered = sorted(values)
    return ordered[min(max(1, math.ceil(pct / 100.0 * len(ordered))), len(ordered)) - 1]


def open_collection(client: Any, name: str, db: Path) -> Any:
    try:
        coll = client.get_collection(name=name)
    except Exception:  # noqa: BLE001 - turned into an actionable message below
        try:
            present = sorted(c.name for c in client.list_collections())
        except Exception:  # noqa: BLE001
            present = []
        die(EXIT_NO_COLLECTION, f"collection {name!r} not found in {db}.\n"
                                f"       Collections present: {present or 'none'}\n       {INGEST_HINT}")
    if coll.count() == 0:
        die(EXIT_NO_COLLECTION, f"collection {name!r} exists in {db} but holds 0 chunks. Re-run ingestion "
                                f"for this strategy.")
    return coll


def run_strategy(strategy: str, client: Any, db: Path, model: Any, questions: list[dict[str, Any]],
                 top_k: int, counter: TokenCounter, prefix: str) -> StrategyResult:
    name = COLLECTIONS[strategy]
    coll = open_collection(client, name, db)
    out = StrategyResult(name=strategy, collection=name, chunk_count=coll.count())
    log(f"[{strategy}] collection {name!r}: {out.chunk_count} chunks")
    # --- Warmup: one embed + one query, discarded, so cold/warm is honest per strategy ---
    log(f"[{strategy}] warmup query (discarded)...")
    _warmup_vec = model.encode(prefix + "warmup query for timing calibration", normalize_embeddings=True)
    coll.query(query_embeddings=[_warmup_vec.tolist()], n_results=min(top_k, coll.count()),
               include=["documents"])
    unresolved: set[str] = set()
    for q in questions:
        t0 = time.perf_counter()  # stage 1 of the <=300ms retrieval budget: embed the query locally
        vector = model.encode(prefix + q["question"], normalize_embeddings=True)
        embed_ms = (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()  # stage 2: vector search, timed separately so the budget is attributable
        raw = coll.query(query_embeddings=[vector.tolist()], n_results=top_k,
                         include=["documents", "metadatas", "distances"])
        search_ms = (time.perf_counter() - t0) * 1000.0

        docs, metas, dists = ((raw.get(k) or [[]])[0] for k in ("documents", "metadatas", "distances"))
        if not docs:
            die(EXIT_NO_COLLECTION, f"collection {name!r} returned 0 results for question {q['number']}. "
                                    f"Present but unusable - re-run ingestion.")
        retrieved: list[str] = []
        records: list[dict[str, Any]] = []
        for doc, meta, dist in zip(docs, metas, dists):
            meta = dict(meta or {})
            ident = next((n for n in (normalise_doc_id(meta.get(k)) for k in SOURCE_KEYS) if n), None)
            if ident is None:
                unresolved.add(json.dumps({k: meta.get(k) for k in SOURCE_KEYS}, sort_keys=True))
                ident = "<unresolved>"
            retrieved.append(ident)
            if dist is None:
                die(EXIT_BAD_INPUT, f"collection {name!r} returned a null distance")
            if dist > 2.0001:
                out.warnings.append(f"saw distance {dist:.3f}, outside the cosine range [0, 2] - the collection "
                                    f"may not have been created with hnsw:space=cosine")
            # Contract v1 normalises similarity to 0-1 (cosine similarity = 1 - distance).
            record = {"content": doc, "score": round(max(0.0, min(1.0, 1.0 - dist)), 4)}
            record.update({k: meta[k] for k in sorted(meta)})
            records.append(record)

        # NAIVE BASELINE payload: the whole tool result, verbatim, as a naive client would paste it into the
        # prompt. Two counts: compact (the honest floor) and verbose (indented, the worst-case ceiling).
        payload = {"results": records, "query": q["question"], "total_found": len(records)}
        tokens = counter.count(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        tokens_verbose = counter.count(json.dumps(payload, ensure_ascii=False, indent=2))
        expected = set(q["expected_docs"])
        r = QResult(number=q["number"], question=q["question"], expected=q["expected_docs"],
                    retrieved=retrieved, hit_at_1=retrieved[0] in expected,
                    hit_at_k=bool(expected & set(retrieved)), embed_ms=embed_ms, search_ms=search_ms,
                    tokens=tokens, tokens_verbose=tokens_verbose)
        out.results.append(r)
        log(f"  Q{r.number:>2} @1={'Y' if r.hit_at_1 else 'n'} @{top_k}={'Y' if r.hit_at_k else 'n'} "
            f"embed={embed_ms:.1f}ms search={search_ms:.1f}ms tokens={tokens}")
    if unresolved:
        die(EXIT_BAD_INPUT, f"collection {name!r} returned chunks whose document identity cannot be resolved to "
                            f"a file under {CORPUS_ROOT}.\n"
                            f"       Looked for metadata keys {SOURCE_KEYS} holding a path like 'amazon/returns.md'.\n"
                            f"       Saw: {sorted(unresolved)[:3]}\n"
                            f"       Refusing to score: unresolved sources would silently read as 0% recall. Fix "
                            f"the ingester's metadata.")
    return out


# --- Scorecard rendering ---
INTRO = """## Read this before reading any percentage

**n = {n}.** Every recall figure below is over **{n} scoreable questions**, not the 28 in `eval/eval_set.md`. One question is worth **{pts:.2f} percentage points**, so a single miss moves Recall@{k} by roughly 9 points. A recall percentage quoted without its n is misleading, which is why n is printed beside every figure in this document.

The other {rest} questions are records, cross-server, actions and unanswerables. They are not silently dropped: they appear in the scorecard below marked `n/a - needs phase 2`, `n/a - needs phase 3` or `n/a - needs client`.

At n={n}: Recall@5 >= 85% allows at most **1 miss** (10/11 = 90.9% passes, 9/11 = 81.8% fails). Recall@1 >= 60% allows at most **4 misses** (7/11 = 63.6%).
"""

OUTRO = """## How to read this scorecard

- **Retrieval only.** No chat LLM is called by this harness, and none will be called by the server. Rows needing generated answers, records, actions or another intern's server are marked `n/a` and left in the table, so the coverage gap is visible rather than implied.
- **COLD vs WARM.** Each strategy runs a warmup query (embed + search, discarded) before scoring, so the cold row is a fair per-strategy measurement rather than an artifact of which strategy loaded the model. p95 over {warm} warm samples is the nearest-rank value, i.e. the maximum observed - indicative, not tight.
- **Two token baselines.** Compact JSON (minimal separators) is the honest floor; verbose JSON (indented) is the worst-case ceiling. The >= 40% reduction target is measured against the compact baseline.
- **Winner selection.** The winner is decided by: (1) Recall@5, (2) latency p95 <= 300 ms gate, (3) Recall@1 tiebreaker, in that order. A strategy that fails the latency gate cannot be the winner unless every strategy fails it.
- **Exit code** reports whether the harness ran, not whether the targets passed. A FAIL row is a measurement, not a crash.
"""


def verdict(value: float, target: float, higher_is_better: bool = True) -> str:
    return "**PASS**" if (value >= target if higher_is_better else value <= target) else "**FAIL**"


def scorecard_rows(sr: StrategyResult, top_k: int, records_res: RecordScoreResult | None = None) -> list[tuple[str, str, str, str, str]]:
    """One strategy's rows: (metric, how measured, target, measured, verdict). Rows that cannot be
    measured yet are kept, with '-' as the value and an n/a marker as the verdict."""
    n, warm = sr.n, len(sr.warm)
    k_note = "" if top_k == 5 else f"; measured at k={top_k}, target stated for k=5"
    budget = "part of the <= 300 ms retrieval budget"
    rows: list[tuple[str, str, str, str, str]] = [
        (f"Recall@{top_k} (documents)", f"any expected doc anywhere in top-{top_k}, n={n}{k_note}", ">= 85%",
         sr.cell(), verdict(sr.recall(), 85.0)),
        ("Recall@1 (documents)", f"top-ranked result is an expected doc, n={n}", ">= 60%",
         sr.cell(at_1=True), verdict(sr.recall(at_1=True), 60.0)),
    ]

    # Structured Records rows (measured from records_res if available)
    if records_res is not None:
        rec_n = records_res.total_count
        rows += [
            ("Records: query correctness", f"exact lookup and filtering over SQLite, n={rec_n}", ">= 90%",
             f"{records_res.accuracy_pct:.1f}% ({records_res.passed_count}/{rec_n})",
             verdict(records_res.accuracy_pct, 90.0)),
            ("Records: numerical accuracy", "exact amounts, totals, and counts matching ground truth", "100%",
             "100.0%" if records_res.numerical_accuracy_passed else "0.0%",
             "**PASS**" if records_res.numerical_accuracy_passed else "**FAIL**"),
            ("Records: empty-result honesty", "empty result for non-existent order (Q28)", "100%",
             "100.0% (Q28)" if records_res.empty_result_honesty_passed else "0.0%",
             "**PASS**" if records_res.empty_result_honesty_passed else "**FAIL**"),
        ]
    else:
        rows += [
            ("Records: query correctness", "SQLite dataset not built", ">= 90%", "-", NA_CLIENT),
            ("Records: numerical accuracy", "SQLite dataset not built", "100%", "-", NA_CLIENT),
            ("Records: empty-result honesty", "SQLite dataset not built", "100%", "-", NA_CLIENT),
        ]

    rows += [(m, h, t, "-", v) for m, h, t, v in NA_ROWS]
    for label, vals in (("query embedding", [r.embed_ms for r in sr.warm]),
                        ("vector search", [r.search_ms for r in sr.warm])):
        rows += [(f"Latency: {label}, WARM p{p}", f"timed as its own stage, nearest-rank, n={warm}", budget,
                  f"{percentile(vals, p):.1f} ms", "-") for p in (50, 95)]
    total = [r.total_ms for r in sr.warm]
    rows += [(f"Latency: retrieval total, WARM p{p}", f"embed + search, cold query discarded, n={warm}",
              "<= 300 ms", f"{percentile(total, p):.1f} ms", verdict(percentile(total, p), 300.0, False))
             for p in (50, 95)]
    rows += [
        ("Latency: retrieval total, COLD", f"first query after model load (Q{sr.cold.number}), 1 sample",
         "reported separately, no gate",
         f"{sr.cold.total_ms:.1f} ms (embed {sr.cold.embed_ms:.1f} + search {sr.cold.search_ms:.1f})", "-"),
        ("Latency: end-to-end p50", "needs the client + chat model", "<= 4 s", "-", NA_CLIENT),
        ("Latency: end-to-end p95", "needs the client + chat model", "<= 10 s", "-", NA_CLIENT),
        ("Latency: MCP transport overhead", "needs the MCP server", "<= 100 ms", "-", "n/a - needs phase 1 server"),
    ]

    if records_res is not None:
        rows += [
            ("Latency: structured query, WARM p50", "direct SQLite query execution time, n=11", "<= 100 ms",
             f"{records_res.p50_ms:.2f} ms", verdict(records_res.p50_ms, 100.0, False)),
            ("Latency: structured query, WARM p95", "direct SQLite query execution time, n=11", "<= 100 ms",
             f"{records_res.p95_ms:.2f} ms", verdict(records_res.p95_ms, 100.0, False)),
        ]
    else:
        rows += [
            ("Latency: structured query", "needs the phase-2 SQLite tools", "<= 100 ms", "-", NA_CLIENT),
        ]

    rows += [
        ("Tokens: NAIVE BASELINE (compact)", f"verbatim top-{top_k} tool result, compact JSON, mean n={n}",
         "BASELINE - the number to beat", f"{sr.mean_tokens:.0f} tokens/query", "BASELINE"),
        ("Tokens: NAIVE BASELINE (verbose)", f"verbatim top-{top_k} tool result, indented JSON, mean n={n}",
         "BASELINE - worst case", f"{sr.mean_tokens_verbose:.0f} tokens/query", "BASELINE"),
        ("Tokens: reduction vs NAIVE BASELINE", "needs the compaction layer, not built", ">= 40% cut", "-", NA_CLIENT),
        ("Robustness suite (9 cases)", "needs a running server + client", "no crashes", "-", NA_CLIENT),
    ]
    return rows


def render(strategies: list[StrategyResult], top_k: int, counter: TokenCounter, gt_path: Path, db: Path,
           prefix: str, model_load_ms: float, records_res: RecordScoreResult | None = None) -> str:
    n = strategies[0].n
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    L: list[str] = ["# Evaluation Scorecard - Retail / E-commerce (Intern 3)", "",
                    f"Generated {stamp} by `eval/harness.py`. Phase 1 (Documents) + Phase 2 (Records).", "",
                    "| Run parameter | Value |", "|---|---|"]
    a = L.append
    for key, val in (("Ground truth", f"`{rel(gt_path)}`"), ("Chroma path", f"`{db}`"),
                     ("Embedding model", f"`{EMBED_MODEL}` (local, CPU; never on GB10)"),
                     ("Model load (one-off)", f"{model_load_ms:.0f} ms"),
                     ("Query prefix", f"`{prefix}`" if prefix else "none"), ("top_k", str(top_k)),
                     ("Token counting", counter.label),
                     ("Strategies", ", ".join(f"{s.name} -> `{s.collection}` ({s.chunk_count} chunks)"
                                              for s in strategies))):
        a(f"| {key} | {val} |")
    a("")
    a(INTRO.format(n=n, pts=100.0 / n, k=top_k, rest=28 - n))

    # One table, one column of measured values per strategy, so the two chunking strategies are
    # scored side by side and the winner is read off the same row.
    a("## Scorecard")
    a("")
    a("| Metric | How measured | Target | " + " | ".join(s.name for s in strategies) + " | Verdict |")
    a("|---|---|---|" + "---|" * (len(strategies) + 1))
    for group in zip(*[scorecard_rows(s, top_k, records_res) for s in strategies]):
        verdicts = [g[4] for g in group]
        joined = (verdicts[0] if len(set(verdicts)) == 1
                  else " / ".join(f"{s.name}: {v}" for s, v in zip(strategies, verdicts)))
        a(f"| {group[0][0]} | {group[0][1]} | {group[0][2]} | " + " | ".join(g[3] for g in group) + f" | {joined} |")
    a("")
    if len(strategies) > 1:
        any_passes_latency = any(s.passes_latency() for s in strategies)
        def winner_key(s: StrategyResult) -> tuple:
            return (s.recall(), s.passes_latency() if any_passes_latency else True, s.recall(at_1=True))
        best = max(strategies, key=winner_key)
        tied_with = [s.name for s in strategies if s.recall() == best.recall() and s is not best]
        notes: list[str] = []
        if tied_with:
            notes.append(
                f"`{best.name}` tied on Recall@{top_k} with {', '.join(f'`{n}`' for n in tied_with)}, "
                f"so the tie was broken on Recall@1 "
                f"({best.recall(at_1=True):.1f}% vs "
                f"{', '.join(f'{s.recall(at_1=True):.1f}%' for s in strategies if s.name in tied_with)})"
            )
        if any_passes_latency and not all(s.passes_latency() for s in strategies):
            failed = [s.name for s in strategies if not s.passes_latency()]
            notes.append(f"{', '.join(failed)} excluded: p95 latency > 300 ms")
        note_str = f" — {'; '.join(notes)}" if notes else ""
        a(f"**Measured winner: `{best.name}`**{note_str}. Winner decided by Recall@{top_k}, "
          f"latency gate (p95 ≤ 300 ms), then Recall@1 — not by preference.")
        a("")
    for w in dict.fromkeys(w for s in strategies for w in s.warnings):
        a(f"> WARNING: {w}")
        a("")

    # Structured Records detail
    if records_res is not None:
        a(f"### Per-question detail - Structured Records (n={records_res.total_count})")
        a("")
        a("| # | Question | Tool Called | Arguments | Latency | Status |")
        a("|---|---|---|---|---|---|")
        for item in records_res.items:
            args_str = ", ".join(f"{k}={v!r}" for k, v in item.arguments.items())
            a(f"| {item.number} | {item.question.replace('|', '/')} | `{item.tool}` | `{args_str}` | {item.latency_ms:.2f} ms | {'**PASS**' if item.passed else '**FAIL**'} |")
        a("")

    for sr in strategies:
        a(f"### Per-question detail - Document Retrieval `{sr.name}` (n={sr.n})")
        a("")
        a(f"| # | Question | Top-1 retrieved | @1 | @{top_k} | Retrieval ms | Tokens (compact) | Tokens (verbose) |")
        a("|---|---|---|---|---|---|---|---|")
        for r in sr.results:
            a(f"| {r.number} | {r.question.replace('|', '/')} | `{r.retrieved[0]}` | "
              f"{'Y' if r.hit_at_1 else 'n'} | {'Y' if r.hit_at_k else 'n'} | "
              f"{r.total_ms:.1f}{' *(cold)*' if r is sr.cold else ''} | {r.tokens} | {r.tokens_verbose} |")
        for r in (r for r in sr.results if not r.hit_at_k):
            a(f"- **Q{r.number} missed @{top_k}**: expected one of `{', '.join(r.expected)}`; "
              f"got `{', '.join(r.retrieved)}`.")
        if any(not r.hit_at_k for r in sr.results):
            a("")
    a(OUTRO.format(warm=strategies[0].n - 1))
    return "\n".join(L) + "\n"


# --- Entry point ---
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval/harness.py", formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                               description="Run the retail eval set against the Chroma index and print the scorecard.")
    p.add_argument("--strategy", choices=["heading", "packed", "both"], default="both",
                   help="which chunking strategy's collection to score")
    p.add_argument("--top-k", type=int, default=5, help="results requested per query")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the scorecard")
    p.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH,
                   help="ground truth JSON (the eval set is data, not code)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Chroma persistent directory built by ingestion")
    p.add_argument("--host", default=os.environ.get("CHROMA_HOST", "127.0.0.1"),
                   help="ChromaDB host (default: 127.0.0.1 or CHROMA_HOST)")
    p.add_argument("--port", type=int, default=int(os.environ.get("CHROMA_PORT", "8100")),
                   help="ChromaDB port (default: 8100 or CHROMA_PORT)")
    p.add_argument("--model", default=EMBED_MODEL, help="local sentence-transformers model")
    p.add_argument("--query-prefix", default="", help="prefix prepended to every query before embedding; bge "
                   "recommends 'Represent this sentence for searching relevant passages: '. Default off, matching "
                   "a server that does no query rewriting")
    p.add_argument("--tokenizer", choices=["auto", "tiktoken", "hf"], default="auto",
                   help="how to count naive-baseline tokens; the choice is named in the scorecard")
    args = p.parse_args(argv)
    if not 1 <= args.top_k <= 50:
        p.error("--top-k must be between 1 and 50")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.top_k != 5:
        log(f"NOTE: --top-k {args.top_k}; the brief's Recall target is stated for k=5.")
    questions = load_ground_truth(args.ground_truth, known_corpus_docs())
    log(f"ground truth: {len(questions)} scoreable questions from {rel(args.ground_truth)} "
        f"(1 question = {100.0 / len(questions):.2f} points)")
    if not args.db.is_dir():
        die(EXIT_NO_COLLECTION, f"Chroma directory not found: {args.db}\n       {INGEST_HINT}")
    try:  # imported here so --help and ground-truth validation work without the heavy deps installed
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        die(EXIT_BAD_INPUT, f"a required package is missing ({exc}). Install both: "
                            f"pip install chromadb sentence-transformers")

    log(f"loading embedding model {args.model!r} (local, CPU)...")
    t0 = time.perf_counter()
    try:
        model = SentenceTransformer(args.model)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        die(EXIT_BAD_INPUT, f"could not load {args.model!r}: {type(exc).__name__}: {exc}")
    model_load_ms = (time.perf_counter() - t0) * 1000.0
    log(f"  model loaded in {model_load_ms:.0f} ms")
    counter = build_token_counter(args.tokenizer, model)

    try:
        client = chromadb.HttpClient(host=args.host, port=args.port)
        client.heartbeat()
        log(f"  connected to ChromaDB via HttpClient at {args.host}:{args.port}")
    except Exception as exc:
        log(f"  could not connect to ChromaDB at {args.host}:{args.port} ({exc}); falling back to PersistentClient at {args.db}")
        client = chromadb.PersistentClient(path=str(args.db))

    names = ["heading", "packed"] if args.strategy == "both" else [args.strategy]
    strategies = [run_strategy(nm, client, args.db, model, questions, args.top_k, counter, args.query_prefix)
                  for nm in names]

    log("evaluating structured operational records...")
    records_res = evaluate_records(args.ground_truth)
    log(f"  records evaluated: {records_res.passed_count}/{records_res.total_count} passed ({records_res.accuracy_pct:.1f}%), p50={records_res.p50_ms:.2f}ms")

    report = render(strategies, args.top_k, counter, args.ground_truth, args.db, args.query_prefix, model_load_ms, records_res)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    log(f"scorecard written to {args.out}")
    print(report, end="")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
