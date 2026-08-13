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

`MCP_TRANSPORT=stdio|http` is also supported. With the pinned `mcp==1.27.2`, the
project's `http` switch runs FastMCP's SSE transport at `/sse` (with messages at
`/messages/`), not an invented FastMCP transport called `http`.

## Exposed MCP capabilities

- Tool: `kb_retail_search(query, top_k=5, filters={document_type?})`
- Resource: `kb_retail_documents` at `kb://retail/documents`
- Prompt: `kb_retail_search_template`

Tool results and application errors are compact JSON strings matching
`contract/contract_v1.md`. Empty results are successful responses. MCP/JSON-RPC
parse errors remain framework-level protocol errors.
