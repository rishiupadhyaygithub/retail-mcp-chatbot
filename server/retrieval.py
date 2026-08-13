"""Frozen Phase A retrieval interface used by the evaluation harness and MCP server.

This module deliberately contains no MCP or chat-model code.  It is the single
place where the selected collection, local embedder and cosine-distance score
conversion are defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHROMA_PATH = REPO_ROOT / "data" / "chroma"
COLLECTION_NAME = "retail_docs_heading"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


class RetrievalUnavailable(RuntimeError):
    """Raised when the locally persisted retrieval dependencies cannot be opened."""


class RetrievalFailure(RuntimeError):
    """Raised when a valid retrieval request cannot be completed."""


@dataclass(frozen=True)
class SearchResult:
    content: str
    source: str
    source_title: str
    section: str
    score: float
    chunk_id: str


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    query: str

    @property
    def total_found(self) -> int:
        return len(self.results)


def _document_title(content: str, fallback: str) -> str:
    """Recover the H1 title that Phase A prefixes to every stored chunk."""
    first_line = content.lstrip().split("\n", 1)[0].strip()
    return first_line[2:].strip() if first_line.startswith("# ") else fallback


def cosine_distance_to_score(distance: float) -> float:
    """Map Chroma cosine distance to the contract v1 §4 similarity score [0, 1].

    `score = 1 - distance`, clamped. Chroma's cosine distance is `1 - cos`, so
    this is the cosine similarity itself: identical text scores 1.0 and an
    unrelated passage scores about 0.

    The earlier mapping was `1 - distance / 2`, which spreads the full [-1, 1]
    cosine range across [0, 1] and is defensible in isolation — but it puts an
    unrelated passage at **0.5**, and contract v1 §4 promises a score
    "normalized to 0-1 across all four servers". A client that thresholds at 0.5
    would have treated noise as a half-decent match, and a teammate using the
    conventional `1 - distance` would have produced numbers that look like ours
    and mean something different. Ranking is unaffected either way: both are
    monotonic in distance, so no recall figure moves.

    Proposed to the team as the shared convention for contract v1.1.
    """
    return round(max(0.0, min(1.0, 1.0 - distance)), 4)


class RetailRetrieval:
    """One initialized connection to the frozen Phase A collection and embedder."""

    def __init__(
        self,
        chroma_path: Path = CHROMA_PATH,
        collection_name: str = COLLECTION_NAME,
        model_name: str = EMBEDDING_MODEL,
    ) -> None:
        self.chroma_path = Path(chroma_path)
        self.collection_name = collection_name
        self.model_name = model_name
        self._client: Any | None = None
        self._collection: Any | None = None
        self._model: Any | None = None

    def initialize(self) -> None:
        """Load all local dependencies once; safe to call before every request."""
        if self._collection is not None and self._model is not None:
            return
        try:
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer

            # A retrieval server should not emit Chroma telemetry or make any
            # outbound request; its only dependency is the local persisted DB.
            client = chromadb.PersistentClient(
                path=str(self.chroma_path),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.get_collection(name=self.collection_name)
            if collection.count() == 0:
                raise RetrievalUnavailable(
                    f"collection {self.collection_name!r} exists but is empty"
                )
            # The frozen Phase A model is already cached locally.  Keeping this
            # offline prevents an optional Hugging Face metadata probe from
            # turning a healthy local server into a network dependency.
            model = SentenceTransformer(
                self.model_name, device="cpu", local_files_only=True
            )
        except RetrievalUnavailable:
            raise
        except Exception as exc:  # dependencies and local data are operational failures
            raise RetrievalUnavailable("retail retrieval is unavailable") from exc

        self._client = client
        self._collection = collection
        self._model = model

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_type: str | None = None,
    ) -> SearchResponse:
        self.initialize()
        assert self._collection is not None
        assert self._model is not None
        try:
            query_vector = self._model.encode(query, normalize_embeddings=True).tolist()
            request: dict[str, Any] = {
                "query_embeddings": [query_vector],
                "n_results": min(top_k, self._collection.count()),
                "include": ["documents", "metadatas", "distances"],
            }
            if document_type is not None:
                request["where"] = {"document_type": document_type}
            raw = self._collection.query(**request)
        except Exception as exc:
            raise RetrievalFailure("retail search could not be completed") from exc

        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        results: list[SearchResult] = []
        for content, metadata, distance in zip(documents, metadatas, distances):
            meta = dict(metadata or {})
            if not isinstance(content, str) or not isinstance(distance, (int, float)):
                raise RetrievalFailure("retail search returned an invalid stored record")
            source = str(meta.get("source", ""))
            chunk_id = str(meta.get("chunk_id", ""))
            if not source or not chunk_id:
                raise RetrievalFailure("retail search returned an incomplete stored record")
            results.append(
                SearchResult(
                    content=content,
                    source=source,
                    source_title=_document_title(content, source),
                    section=str(meta.get("section", "")),
                    score=cosine_distance_to_score(float(distance)),
                    chunk_id=chunk_id,
                )
            )
        return SearchResponse(results=results, query=query)

    def documents(self) -> list[dict[str, str]]:
        """Return deterministic, embedding-free corpus discovery information."""
        self.initialize()
        assert self._collection is not None
        try:
            raw = self._collection.get(include=["documents", "metadatas"])
        except Exception as exc:
            raise RetrievalFailure("retail document list could not be completed") from exc

        documents = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []
        by_source: dict[str, dict[str, str]] = {}
        for content, metadata in zip(documents, metadatas):
            meta = dict(metadata or {})
            source = str(meta.get("source", ""))
            if source and isinstance(content, str):
                by_source[source] = {
                    "id": source,
                    "title": _document_title(content, source),
                    "document_type": str(meta.get("document_type", "")),
                }
        return [by_source[source] for source in sorted(by_source)]
