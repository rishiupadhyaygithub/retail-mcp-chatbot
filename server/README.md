# Retail MCP server

Thin MCP adapter over the frozen Phase A retrieval baseline.

**Rule: this server never calls an LLM.** It embeds locally with
`BAAI/bge-small-en-v1.5` and queries `retail_docs_heading` in `data/chroma`.

## Run

```bash
# Local MCP clients, including Claude Desktop:
python3 server/main.py --transport stdio

# Interop transport: listens on every LAN interface at port 8003.
python3 server/main.py --transport http --host 0.0.0.0 --port 8003
```

`MCP_TRANSPORT=stdio|http|sse` is also supported. Contract v1 §7 names the
network transport `http`; on the pinned `mcp==2.0.0` that maps to the SDK's
**Streamable HTTP** transport, endpoint **`/mcp`**. Point interop clients at
`http://10.10.180.132:8003/mcp` — verified against that address, not just
localhost.

Host and port are arguments to `run_server`, not to `create_server`: mcp 2.0.0
moved them onto the transport, and its default host is `127.0.0.1`, so binding
every interface is always explicit here and never an inherited default.

The `initialize` handshake reports protocol version **`2025-11-25`**. The SDK's
`LATEST_PROTOCOL_VERSION` is `2026-07-28`, but `2025-11-25` is the newest entry
in its negotiable `HANDSHAKE_PROTOCOL_VERSIONS`. See design document §2.

`--transport sse` still selects the SDK's SSE transport (`/sse`, messages at
`/messages/`). MCP deprecated SSE in spec revision 2025-03-26 and this project
targets 2026-07-28, so SSE is kept only for a teammate's client that has not
migrated yet. It is never the default and never the demo path.

`tests/test_transport.py` starts the server on a real socket and drives it with
a real MCP client, so a regression back to SSE fails the suite.

## Exposed MCP capabilities

- Tool: `kb_retail_search(query, top_k=5, filters={document_type?})`
  - `top_k` is capped at **20** (`server/schemas.MAX_TOP_K`). Contract v1 §3 sets
    no ceiling; without one, `top_k=100000` returned all 97 chunks / 10,120
    tokens against a 586-token naive baseline. Over-cap requests are refused with
    `invalid_parameter` rather than silently clamped, so `total_found` never
    disagrees with the request. Raised for the team as a contract v1.1 item.
- Resource: `kb_retail_documents` at `kb://retail/documents`
- Prompt: `kb_retail_search_template`

Tool results and application errors are compact JSON strings matching
`contract/contract_v1.md`. Empty results are successful responses. MCP/JSON-RPC
parse errors remain framework-level protocol errors.
