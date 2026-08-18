# Phase B Contract Conformance Matrix — Retail

| Contract requirement | Implementation | Verification |
|---|---|---|
| `kb_retail_search` name and description | `server/main.py` | `test_discovery_exposes_the_frozen_tool_schema` |
| Required `query`; optional integer `top_k`; `filters.document_type` only | strict advertised schema plus `validate_search_request` | discovery and malformed-input tests |
| `top_k` ceiling (local addition — contract v1 §3 states none) | `schemas.MAX_TOP_K = 20`, refused not clamped | `test_top_k_above_the_cap_returns_an_application_error` |
| Results fields and successful empty array | `format_search_response` | MCP tool contract test; empty-result test |
| Score is a 0–1 higher-is-better similarity | `retrieval.cosine_distance_to_score`: `1 - distance`, clamped — cosine similarity itself, so unrelated text scores ~0 rather than 0.5 | frozen retrieval test; live check: relevant 0.82 vs unrelated 0.49 |
| Stable `retail-doc-<n>:chunk-<n>` ID | Phase A metadata reused unchanged | frozen retrieval test |
| Invalid tool arguments use `{error,message,retryable}` | custom FastMCP argument bridge + `server/schemas.py` | missing, wrong-type, and unknown-parameter tests |
| Malformed JSON-RPC | MCP framework boundary | live MCP-client test |
| One document-list resource | `kb://retail/documents` | resource discovery/read test |
| One useful prompt | `kb_retail_search_template` | prompt discovery/get test |
| stdio plus network HTTP | CLI maps `http` to MCP Streamable HTTP at `/mcp`, `0.0.0.0:8003`; deprecated SSE stays selectable via `--transport sse` | `test_streamable_http_serves_discovery_and_tool_calls_over_a_socket`, `test_contract_http_maps_to_streamable_http_not_sse`; live check against `10.10.180.132:8003` |
| Negotiated protocol version | `2025-11-25` — the newest entry in the SDK's `HANDSHAKE_PROTOCOL_VERSIONS`, on both `mcp==2.0.0` and `mcp==1.27.2` | live `initialize` over stdio and Streamable HTTP; see design document §2 |
| No LLM / no GB10 dependency | `server/retrieval.py` only loads local Chroma (port 8100) + BGE-M3 | code review and live retrieval test |
