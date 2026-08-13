"""Public-contract tests for the frozen retail retrieval baseline."""

from retrieval import RetailRetrieval


def test_search_reuses_heading_collection_and_normalizes_scores() -> None:
    retrieval = RetailRetrieval()

    response = retrieval.search("how long till they get their money back on a return?", top_k=1)

    assert response.total_found == 1
    result = response.results[0]
    assert result.chunk_id.startswith("retail-doc-")
    # Recorded heading-baseline top result for this Phase A question.
    assert result.source == "bestbuy/returns.md"
    assert 0.0 <= result.score <= 1.0
