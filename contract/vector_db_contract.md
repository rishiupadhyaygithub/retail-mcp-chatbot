# Vector DB Access Contract (Approach 1)

Scope: direct access to each intern's vector database, outside MCP. This governs approach 1, where one server queries all four industries' vector stores directly rather than going through each other's MCP tools.

All four interns' vector DBs must conform to this, even if your own client uses approach 2 and never calls this interface yourself. The approach-1 server depends on every DB behaving identically.

Does not cover phase 2/3 relational stores. Vector DB access only, for now.

---

## 1. Store technology

Chroma, run as its own external service (`chroma run`), not embedded. Every intern's vector DB must be reachable this way, since direct access requires a real network connection, not an in-process library call.

## 2. Network addresses

| Intern | Industry | Vector DB host/IP | Port |
|---|---|---|---|
| 1 | Banking | 10.10.180.175 | 8001 |
| 2 | Hospitality | _pending_ | _pending_ |
| 3 | Retail | 10.10.180.132 | 8100 |
| 4 | Telecom | 10.10.180.178 | 8004 |

Bind to your machine's actual LAN IP on `0.0.0.0`, not `127.0.0.1`.

## 3. Embedding model

`BAAI/bge-m3`, the shared embedding model.

The approach-1 server runs its own local embedder and passes query vectors directly into your Chroma instance. It uses the model that was agreed on. If your database was ingested with a different model, vector similarity returns noise.

Ingest with `bge-m3`. No exceptions, no per-intern substitutions.

## 4. Collection names

Each intern creates one collection. Pattern: `<industry>_docs`.

| Industry | Collection name |
|---|---|
| Banking | `banking_docs` |
| Hospitality | `hospitality_docs` |
| Retail | `retail_docs` |
| Telecom | `telecom_docs` |

Exact names, lowercase, underscore. Do not add suffixes like `_v1`, `_final`, or `_embedded`.

## 5. Distance function

Cosine distance (`hnsw:space`: `cosine`) on every collection.

```python
collection = client.get_or_create_collection(
    name="<industry>_docs",
    metadata={"hnsw:space": "cosine"}
)
```

Do not use `l2` or `ip` (inner product). The approach-1 server assumes cosine distance everywhere; mixed distance functions produce incomparable scores across industries.

## 6. Stored metadata fields

Every chunk written to Chroma must include these metadata fields, exact key names, string values unless noted:

| Field | Type | Description | Example |
|---|---|---|---|
| `source` | string | document title | `"Returns and Refunds Policy"` |
| `chunk_id` | string | `<industry>-doc-<n>:chunk-<n>` | `"retail-doc-3:chunk-1"` |
| `document_type` | string | document category | `"returns"` |
| `brand` | string | brand / provider name | `"amazon"` |
| `section` | string | heading, if available | `"Refund timing"` |
| `word_count` | int | prose word count | `42` |

The approach-1 server needs `source` and `chunk_id` for citation generation. If these keys are missing or named differently (`file_name`, `id`, `doc_id`), citations break.

## 7. What the query returns

The approach-1 server executes queries against your Chroma instance:

```python
results = collection.query(
    query_embeddings=[query_vector],
    n_results=top_k,
    include=["documents", "metadatas", "distances"]
)
```

Your Chroma must return all three: documents (the text content), metadatas (the fields above), and distances (for score computation).

## 8. Corpus size expectation

Phase 1 scope: 15-40 documents per industry, ingested and ready. The approach-1 server assumes every DB is populated on connection, not empty waiting for an ingest job.

## 9. Score normalization

Chroma returns cosine distance in the range `[0, 2]`. The approach-1 server is responsible for its own score normalization before passing results to the LLM. Your Chroma instance only needs to return the raw distances correctly from a `cosine`-configured collection.

## 10. Checklist before declaring your vector DB ready

- [x] Chroma running as a standalone service (`chroma run --host 0.0.0.0 --port <port> --path <path>`)
- [x] Reachable from another machine: `curl http://<your-ip>:<port>/api/v1/heartbeat` returns `200`
- [x] Collection exists with exact name `<industry>_docs`
- [x] Ingested with `BAAI/bge-m3` (1024-dimensional vectors)
- [x] `hnsw:space` set to `cosine`
- [x] Every chunk has `source`, `chunk_id`, `document_type` in metadata
- [x] Host/IP and port added to the table in §2 above
