# Phase B Contract Conformance Matrix — Retail

| Contract requirement | Implementation | Verification |
|---|---|---|
| `kb_retail_search` name and description | `server/main.py` | `test_discovery_exposes_the_frozen_tool_schema` |
| Required `query`; optional integer `top_k`; `filters.document_type` only | strict advertised schema plus `validate_search_request` | discovery and malformed-input tests |
| `top_k` ceiling (local addition — contract v1 §3 states none) | `schemas.MAX_TOP_K = 20`, refused not clamped | `test_top_k_above_the_cap_returns_an_application_error` |
| Results fields and successful empty array | `format_search_response` | MCP tool contract test; empty-result test |
| Score is a 0–1 higher-is-better similarity | `retrieval.cosine_distance_to_score`: `1 - distance / 2` | frozen retrieval test |
| Stable `retail-doc-<n>:chunk-<n>` ID | Phase A metadata reused unchanged | frozen retrieval test |
| Invalid tool arguments use `{error,message,retryable}` | custom FastMCP argument bridge + `server/schemas.py` | missing, wrong-type, and unknown-parameter tests |
| Malformed JSON-RPC | MCP framework boundary | live MCP-client test |
| One document-list resource | `kb://retail/documents` | resource discovery/read test |
| One useful prompt | `kb_retail_search_template` | prompt discovery/get test |
| stdio plus network HTTP | CLI maps `http` to MCP Streamable HTTP at `/mcp`, `0.0.0.0:8003`; deprecated SSE stays selectable via `--transport sse` | `test_streamable_http_serves_discovery_and_tool_calls_over_a_socket`, `test_contract_http_maps_to_streamable_http_not_sse` |
| No LLM / no GB10 dependency | `server/retrieval.py` only loads local Chroma + BGE | code review and live retrieval test |
