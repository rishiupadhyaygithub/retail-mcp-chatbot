# data/

Corpus sources list, ingestion scripts, dataset generator.

- `sources.md` — 22 retail documents in the RAG corpus, URLs + retrieval dates pinned ✅
- `corpus/<company>/<topic>.md` — the sourced pages (Amazon, Best Buy, IKEA, Target) ✅
- ingestion script — chunk + embed (local `bge-small-en-v1.5`) + load into Chroma _(to add — Phase 1)_
