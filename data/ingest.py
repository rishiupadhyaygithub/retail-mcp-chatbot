#!/usr/bin/env python3
"""Corpus ingester for the Retail Contact Center Knowledge Assistant (Intern 3).

Walks data/corpus/<brand>/*.md, chunks each document, embeds every chunk locally with
BAAI/bge-small-en-v1.5 (CPU), and writes to a persistent ChromaDB collection under
data/chroma/. Two strategies exist so the baseline scorecard picks a winner by
measured Recall@5, not by opinion:

  --strategy heading   one chunk per "##" section  -> "retail_docs_heading"
  --strategy packed    "##" sections packed to ~100 words -- the default, and the
                       fix for heading-only chunks being ~8x too small
                       -> "retail_docs_packed"

Document numbering (the <n> in "retail-doc-<n>") is assigned once from the sorted
document list and is IDENTICAL across both strategies, so the two scorecards are
comparable and the same passage cites the same way whichever collection answered.

This script NEVER calls a chat LLM and never contacts the shared GB10 box.
Retrieval in the server, reasoning in the client -- the one unbreakable rule.

    python3 data/ingest.py [--strategy heading|packed] [--rebuild] [--stats]

--stats is a DRY RUN: chunk, print the sanity table to stdout, exit -- no model
load, no ChromaDB. Cheap enough to run on every change, which is the point: it is
what catches a silent chunking regression. Without --rebuild the script refuses to
write into a non-empty collection rather than producing duplicates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Paths resolved from this file's own location -- no hardcoded absolutes, so the
# script works from a clean checkout wherever it lands.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CORPUS_DIR = SCRIPT_DIR / "corpus"
CHROMA_DIR = SCRIPT_DIR / "chroma"

# Locked constants. Do not tune casually -- measured against the real 22-document
# corpus, and the eval ground truth is pinned to the chunk_ids they produce.
MODEL_NAME = "BAAI/bge-m3"
INDUSTRY = "retail"  # the <industry> in contract v1's "<industry>-doc-<n>:chunk-<n>"

TARGET_WORDS = 100  # packed: aim for this many prose words per chunk
MAX_WORDS = 150     # packed: hard ceiling for a packed chunk
MIN_WORDS = 40      # packed: floor, stops the packer emitting a runt tail
OVERLAP_WORDS = 50  # only used when a single "##" section exceeds MAX_WORDS

COLLECTIONS = {
    "heading": "retail_docs",
    "packed": "retail_docs_packed",
    "retail_docs_heading": "retail_docs_heading",
}
DOCUMENT_TYPES = ("returns", "warranty", "delivery", "payments", "order_tracking")

# document_type comes from the FILENAME STEM, never guessed. Three stems are not
# self-evident; each was decided by reading the file:
#   warranty_terms   (ikea) -> warranty. IKEA publishes its per-range guarantee
#     lengths (25-yr SEKTION kitchens, 10-yr mattresses/sofas/faucets) separately
#     from its short warranty overview. A second warranty document, not a new
#     category -- so IKEA legitimately contributes two "warranty" documents.
#   charged_twice  (amazon) -> payments. Authorization holds vs actual charges,
#     split shipments, re-authorization after an order change. Money movement on
#     the card, not returning goods.
#   refund_timelines (amazon) -> payments. Judgement call: it is triggered BY a
#     return, but the content is purely "when does the money land and why the
#     payment method changes that" (2 business days to process, 3-5 to appear, up
#     to 30 overall). The returns *policy* -- eligibility, the 30-day window --
#     lives in amazon/returns.md. So: returns = windows/eligibility, payments = money.
# Say this out loud, it will show up in the baseline: there is NO amazon/payments.md.
# Amazon's payments coverage is those two special cases, so "what payment methods
# does Amazon accept?" has no gold passage -- a corpus gap, not a retrieval failure.
# Check eval/eval_set.md for such a question before blaming the embedder.
FILENAME_TYPE_MAP = {
    "returns": "returns", "warranty": "warranty", "warranty_terms": "warranty",
    "delivery": "delivery", "payments": "payments", "order_tracking": "order_tracking",
    "charged_twice": "payments", "refund_timelines": "payments",
}

# Pure markdown scaffolding once line markers are stripped (table rules |---|---|,
# horizontal rules). The em dash U+2014 is a real word token here, so not matched.
_SCAFFOLD_TOKEN = re.compile(r"^[-:_|*+=]+$")
_HEADING_MARK = re.compile(r"^(#{1,6})\s*")
_BULLET_MARK = re.compile(r"^([-*+]|\d+\.)\s+")
_QUOTE_MARK = re.compile(r"^>\s*")


def die(message: str) -> "NoReturn":  # noqa: F821
    """Fail loudly. Never silently default, never swallow."""
    print(f"ingest.py: error: {message}", file=sys.stderr)
    raise SystemExit(2)


# "Words" everywhere in this file means PROSE words: YAML frontmatter and markdown
# markers (#, ##, **, -, |) excluded; H1 title, "##" heading text and body included.
# Raw `wc -w` is larger because it counts markers -- not the unit used here.
def prose_word_count(text: str) -> int:
    total = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = _QUOTE_MARK.sub("", s)
        s = _HEADING_MARK.sub("", s)
        s = _BULLET_MARK.sub("", s)
        s = s.replace("**", "").replace("`", "").replace("|", " ")
        total += sum(1 for tok in s.split() if not _SCAFFOLD_TOKEN.match(tok))
    return total


# --- Corpus loading ---
@dataclass
class Unit:
    """One packing unit: a "##" section, or the lead prose before the first one."""
    heading: str | None  # None only for lead prose
    text: str            # raw markdown, heading line included when present
    words: int


@dataclass
class Document:
    index: int           # the <n> in retail-doc-<n>; stable across strategies
    rel_path: str        # corpus-relative, e.g. "ikea/warranty_terms.md"
    brand: str
    title: str           # H1 text, markers stripped
    document_type: str
    units: list[Unit] = field(default_factory=list)

    @property
    def title_words(self) -> int:
        return prose_word_count(self.title)

    @property
    def body_words(self) -> int:
        """What the packer budgets against: the H1 title is prefixed to every
        chunk's embedded text but charged to no chunk's budget."""
        return sum(u.words for u in self.units)

    @property
    def total_words(self) -> int:
        """Whole-document prose words, title included. Reporting only."""
        return self.title_words + self.body_words


def parse_frontmatter(raw: str, rel_path: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        die(f"{rel_path}: missing YAML frontmatter (file must start with '---')")
    end = raw.find("\n---", 3)
    if end == -1:
        die(f"{rel_path}: frontmatter opened with '---' but never closed")
    meta: dict[str, str] = {}
    for line in raw[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            die(f"{rel_path}: unparseable frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, raw[end + 4 :].lstrip("\n")


def split_units(body: str, rel_path: str) -> tuple[str, list[Unit]]:
    """Return (H1 title, units): the "##" sections in order, preceded by a lead unit
    if the document has prose before its first "##". One does (ikea/warranty_terms.md)
    -- its "residential use only" scope rides along rather than being dropped."""
    lines = body.splitlines()
    title, start = "", 0
    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            title, start = _HEADING_MARK.sub("", line.strip()), i + 1
            break
    else:
        die(f"{rel_path}: no H1 title line ('# ...') found")

    units: list[Unit] = []
    heading: str | None = None
    buffer: list[str] = []
    def flush(h: str | None) -> None:
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            units.append(Unit(h, text, prose_word_count(text)))

    for line in lines[start:]:
        if line.startswith("## ") and not line.startswith("### "):
            flush(heading)
            buffer, heading = [line], _HEADING_MARK.sub("", line.strip())
        else:
            buffer.append(line)
    flush(heading)

    if not units:
        die(f"{rel_path}: document has no content after its H1 title")
    return title, units


def load_documents() -> list[Document]:
    if not CORPUS_DIR.is_dir():
        die(f"corpus directory not found: {CORPUS_DIR}")
    # Sorted once by corpus-relative POSIX path: this is what makes chunk_ids
    # reproducible across runs AND identical across the two strategies.
    paths = sorted(CORPUS_DIR.glob("*/*.md"), key=lambda p: p.relative_to(CORPUS_DIR).as_posix())
    if not paths:
        die(f"no documents matched {CORPUS_DIR}/*/*.md")

    docs: list[Document] = []
    for n, path in enumerate(paths, start=1):
        rel_path = path.relative_to(CORPUS_DIR).as_posix()
        stem = path.stem
        if stem not in FILENAME_TYPE_MAP:
            die(f"{rel_path}: filename stem {stem!r} has no document_type mapping. Add it to "
                f"FILENAME_TYPE_MAP with a comment explaining the choice; do not let it default.")
        document_type = FILENAME_TYPE_MAP[stem]
        if document_type not in DOCUMENT_TYPES:
            die(f"{rel_path}: mapped document_type {document_type!r} not in {DOCUMENT_TYPES}")

        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"), rel_path)
        # Cross-check the filename mapping against the frontmatter the corpus was
        # captured with. Disagreement means one of them is wrong; refuse to guess.
        declared = meta.get("document_type")
        if declared is None:
            die(f"{rel_path}: frontmatter has no document_type field")
        if declared != document_type:
            die(f"{rel_path}: document_type disagreement -- frontmatter says {declared!r}, "
                f"filename stem {stem!r} maps to {document_type!r}. Fix the file or fix "
                f"FILENAME_TYPE_MAP; do not ignore this.")

        title, units = split_units(body, rel_path)
        docs.append(Document(n, rel_path, path.parent.name, title, document_type, units))
    return docs


# --- Chunking ---
@dataclass
class Chunk:
    chunk_id: str
    source: str
    title: str
    brand: str
    section: str
    document_type: str
    text: str        # what gets embedded and stored: title + body
    word_count: int  # prose words of the body, title excluded


def _oversize_split(unit: Unit) -> list[Unit]:
    """Re-split a single "##" section that breaches MAX_WORDS on its own, with
    OVERLAP_WORDS of overlap so no clause is orphaned at a boundary. On the current
    corpus this NEVER fires -- the largest section is 74 words. It exists because
    the corpus will grow; it is not claimed as a working feature anywhere."""
    if unit.words <= MAX_WORDS:
        return [unit]
    stride = MAX_WORDS - OVERLAP_WORDS
    if stride <= 0:
        die(f"bad parameters: OVERLAP_WORDS ({OVERLAP_WORDS}) >= MAX_WORDS ({MAX_WORDS})")
    tokens = unit.text.split()
    pieces: list[Unit] = []
    for start in range(0, len(tokens), stride):
        window = tokens[start : start + MAX_WORDS]
        if not window:
            break
        text = " ".join(window)
        pieces.append(Unit(unit.heading, text, prose_word_count(text)))
        if start + MAX_WORDS >= len(tokens):
            break
    return pieces


def _pack(doc: Document) -> list[list[Unit]]:
    """Pack adjacent "##" sections of ONE document until ~TARGET_WORDS. Never
    packs across documents."""
    total = doc.body_words
    if total <= MAX_WORDS:
        return [list(doc.units)]

    n = max(math.ceil(total / MAX_WORDS), round(total / TARGET_WORDS))
    while n > 1 and total / n < MIN_WORDS:
        n -= 1
    aim = total / n

    groups: list[list[Unit]] = []
    current: list[Unit] = []
    current_words = 0
    for unit in doc.units:
        if unit.words > MAX_WORDS:  # oversize section: flush, then emit its pieces alone
            if current:
                groups.append(current)
                current, current_words = [], 0
            groups.extend([p] for p in _oversize_split(unit))
            continue
        if not current or current_words + unit.words > MAX_WORDS:
            if current:
                groups.append(current)
            current, current_words = [unit], unit.words
            continue
        # Close the chunk when adding this unit overshoots `aim` by more than
        # stopping here undershoots it.
        if ((current_words + unit.words) - aim) > (aim - current_words):
            groups.append(current)
            current, current_words = [unit], unit.words
        else:
            current.append(unit)
            current_words += unit.words
    if current:
        groups.append(current)

    # Runt guard: a tail under MIN_WORDS is worse than a slightly fat chunk. Never
    # fires here -- the smallest emitted chunk is 71 words.
    if len(groups) > 1 and sum(u.words for u in groups[-1]) < MIN_WORDS:
        groups[-2].extend(groups.pop())
    return groups


def _group_to_chunk(doc: Document, group: list[Unit], m: int) -> Chunk:
    # "section" is every heading the chunk covers, joined with " | " -- still a
    # string, so contract v1's "section": "heading, if available" holds. Consecutive
    # repeats collapse: an oversize section's pieces each carry the same heading.
    section_parts: list[str] = []
    for h in (u.heading for u in group):
        if h and (not section_parts or section_parts[-1] != h):
            section_parts.append(h)
    section = " | ".join(section_parts) if section_parts else doc.title

    body = "\n\n".join(u.text.strip("\n") for u in group)
    # Title prefixed so a chunk headed only "Exceptions" knows it is IKEA's. It is
    # NOT counted in word_count.
    words = sum(u.words for u in group)
    if words <= 0:
        die(f"{doc.rel_path}: produced an empty chunk at chunk-{m}")
    return Chunk(
        chunk_id=f"{INDUSTRY}-doc-{doc.index}:chunk-{m}",
        source=doc.rel_path, title=doc.title, brand=doc.brand, section=section,
        document_type=doc.document_type, text=f"# {doc.title}\n\n{body}", word_count=words,
    )


def chunk_document(doc: Document, strategy: str) -> list[Chunk]:
    if strategy == "packed":
        groups = _pack(doc)
    elif strategy == "heading":
        units = list(doc.units)
        # Lead prose before the first "##" merges into the first section rather than
        # becoming its own chunk, so this emits exactly one chunk per "##". Nothing
        # is dropped.
        if len(units) > 1 and units[0].heading is None:
            units = [Unit(units[1].heading, units[0].text + "\n\n" + units[1].text,
                          units[0].words + units[1].words)] + units[2:]
        groups = [[u] for u in units]
    else:
        die(f"unknown strategy {strategy!r}")
    return [_group_to_chunk(doc, g, m) for m, g in enumerate(groups, start=1)]


def build_chunks(docs: list[Document], strategy: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        chunks.extend(chunk_document(doc, strategy))
    seen: set[str] = set()
    for c in chunks:
        if c.chunk_id in seen:
            die(f"duplicate chunk_id generated: {c.chunk_id}")
        seen.add(c.chunk_id)
    return chunks


# --- Stats table: the sanity check that catches a silent chunking regression ---
def print_stats(docs: list[Document], chunks: list[Chunk], strategy: str) -> None:
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.source, []).append(c)

    header = f"{'#':>3}  {'document':<30} {'words':>6} {'##':>3} {'chunks':>6}  chunk words"
    rule = "-" * len(header)
    rows = ["", f"strategy: {strategy}   collection: {COLLECTIONS[strategy]}",
            f"corpus:   {CORPUS_DIR}", "", header, rule]
    for doc in docs:
        dchunks = by_doc.get(doc.rel_path, [])
        rows.append(
            f"{doc.index:>3}  {doc.rel_path:<30} {doc.total_words:>6} "
            f"{sum(1 for u in doc.units if u.heading):>3} {len(dchunks):>6}  "
            + ", ".join(str(c.word_count) for c in dchunks)
        )
    rows += [rule, f"{'':>3}  {'TOTAL':<30} {sum(d.total_words for d in docs):>6} "
             f"{sum(1 for d in docs for u in d.units if u.heading):>3} {len(chunks):>6}"]
    sizes = sorted(c.word_count for c in chunks)
    rows += ["", f"documents         : {len(docs)}", f"chunks            : {len(chunks)}",
             f"chunk words min   : {sizes[0]}   median: {int(statistics.median(sizes))}"
             f"   max: {sizes[-1]}   mean: {sum(sizes) / len(sizes):.1f}"]
    if strategy == "packed":
        under = [c.chunk_id for c in chunks if c.word_count < MIN_WORDS]
        over = [c.chunk_id for c in chunks if c.word_count > MAX_WORDS]
        rows.append(f"budget check      : target={TARGET_WORDS} max={MAX_WORDS} "
                    f"min={MIN_WORDS} | {len(under)} under-min, {len(over)} over-max")
        if under or over:
            rows.append(f"  under-min: {under}\n  over-max : {over}")
    print("\n".join(rows) + "\n")


# --- Embedding + ChromaDB ---
def embed(texts: list[str]) -> list[list[float]]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        die(f"sentence-transformers is not installed ({exc}). pip install -r requirements.txt")
    print(f"[ingest] loading {MODEL_NAME} on cpu (once)", file=sys.stderr)
    model = SentenceTransformer(MODEL_NAME, device="cpu")  # loaded ONCE, locally
    print(f"[ingest] embedding {len(texts)} chunks", file=sys.stderr)
    vectors = model.encode(texts, batch_size=32, normalize_embeddings=True,
                           show_progress_bar=False)
    return [v.tolist() for v in vectors]


def write_collection(
    chunks: list[Chunk],
    strategy: str,
    rebuild: bool,
    host: str = "127.0.0.1",
    port: int = 8100,
    collection_name: str | None = None,
) -> str:
    try:
        import chromadb
    except ImportError as exc:
        die(f"chromadb is not installed ({exc}). pip install -r requirements.txt")

    name = collection_name or COLLECTIONS[strategy]
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        endpoint_desc = f"HttpClient at {host}:{port}"
    except Exception as exc:
        print(
            f"[ingest] could not connect to Chroma HttpClient at {host}:{port} ({exc}); "
            f"falling back to PersistentClient at {CHROMA_DIR}",
            file=sys.stderr,
        )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        endpoint_desc = f"PersistentClient at {CHROMA_DIR}"

    if rebuild and name in {c.name for c in client.list_collections()}:
        print(f"[ingest] --rebuild: deleting collection {name}", file=sys.stderr)
        client.delete_collection(name)

    collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
    count = collection.count()
    if count > 0:
        die(f"collection {name!r} already holds {count} records. Refusing to write and create "
            f"duplicates. Re-run with --rebuild to drop and recreate it.")

    vectors = embed([c.text for c in chunks])
    if len(vectors) != len(chunks):
        die(f"embedding returned {len(vectors)} vectors for {len(chunks)} chunks")

    collection.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=vectors,
        metadatas=[{
            "source": c.title,
            "source_path": c.source,
            "title": c.title,
            "brand": c.brand,
            "section": c.section,
            "chunk_id": c.chunk_id,
            "document_type": c.document_type,
            "word_count": c.word_count,
        } for c in chunks],
    )
    written = collection.count()
    if written != len(chunks):
        die(f"wrote {written} records but built {len(chunks)} chunks")
    print(f"[ingest] wrote {written} records to {name} via {endpoint_desc}", file=sys.stderr)
    return name


# --- CLI ---
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest.py",
        description="Chunk, embed and load the retail corpus into ChromaDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"heading = one chunk per '##' section -> 'retail_docs' (default)\n"
               f"packed  = '##' sections packed to ~{TARGET_WORDS} words, {MAX_WORDS} max -> 'retail_docs_packed'\n"
               f"--stats is a DRY RUN: table only, embeds and writes nothing.",
    )
    parser.add_argument("--strategy", choices=sorted(COLLECTIONS), default="heading",
                        help="chunking strategy (default: heading -> retail_docs)")
    parser.add_argument("--collection", default=None,
                        help="explicit collection name (defaults to mapping for strategy)")
    parser.add_argument("--host", default=os.environ.get("CHROMA_HOST", "127.0.0.1"),
                        help="ChromaDB host (default: 127.0.0.1 or CHROMA_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHROMA_PORT", "8100")),
                        help="ChromaDB port (default: 8100 or CHROMA_PORT)")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete and recreate the collection before writing")
    parser.add_argument("--stats", action="store_true",
                        help="dry run: print the chunking sanity table and exit")
    args = parser.parse_args(argv)

    print(f"[ingest] repo root: {REPO_ROOT}", file=sys.stderr)
    docs = load_documents()
    print(f"[ingest] loaded {len(docs)} documents", file=sys.stderr)
    chunks = build_chunks(docs, args.strategy)
    print(f"[ingest] built {len(chunks)} chunks ({args.strategy})", file=sys.stderr)

    if args.stats:
        print_stats(docs, chunks, args.strategy)
        print("[ingest] --stats is a dry run; nothing embedded, nothing written.", file=sys.stderr)
        return 0

    name = write_collection(chunks, args.strategy, args.rebuild, host=args.host, port=args.port, collection_name=args.collection)
    sizes = sorted(c.word_count for c in chunks)
    json.dump({
        "strategy": args.strategy, "collection": name, "chroma_path": str(CHROMA_DIR),
        "embedding_model": MODEL_NAME, "documents": len(docs), "chunks": len(chunks),
        "chunk_words": {"min": sizes[0], "median": int(statistics.median(sizes)),
                        "max": sizes[-1], "mean": round(sum(sizes) / len(sizes), 1)},
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
