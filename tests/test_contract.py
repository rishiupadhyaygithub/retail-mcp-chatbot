"""Application-level contract tests for kb_retail_search."""

from server.schemas import invalid_parameter


def test_invalid_top_k_uses_the_frozen_error_shape() -> None:
    assert invalid_parameter("top_k must be a positive integer") == {
        "error": "invalid_parameter",
        "message": "top_k must be a positive integer",
        "retryable": False,
    }
