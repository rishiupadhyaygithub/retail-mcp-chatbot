# Contract v1

Shared interface contract, phase 1 (search) only. Covers search, plus resources, prompts, errors, and transport, per the task brief §6. Jointly authored by all four interns. Due alongside the main design document, end of Wednesday 12 August 2026. Frozen once agreed, changes require consensus from all four (see the alignment document for process).

---

## 1. Tool naming convention

**Pattern:**

```
kb_<industry>_<verb>[_<noun>]
```

- `kb` = fixed prefix, all tools, all servers.
- `<industry>` = fixed token per intern:

```
banking
hospitality
retail
telecom
```

- `<verb>` = fixed set: `search`, `query`, `create`. (Only `search` is in scope for v1.)
- `<noun>` = not used for `search` (search spans the whole document corpus).

**v1 example:**

```
kb_banking_search
kb_retail_search
kb_hospitality_search
kb_telecom_search
```

---

## 2. Tool description convention

**Template:**

```
"<what it does> for <industry>. Use when <trigger condition>. Do not use for <adjacent thing it is NOT for>."
```

**Example:**

```
kb_banking_search:
"Search banking policy and help documentation (disputes, fraud, KYC, account terms, card blocks). 
Use for questions about rules, policies, or procedures. 
Do not use for questions about a specific customer's actual transactions or account activity."
```

Each intern writes their own description content, following this shared structure.

---

## 3. Search tool input schema (identical across all four servers)

```json
{
  "query": "string, required",
  "top_k": "integer, optional, default 5",
  "filters": {
    "document_type": "string, optional"
  }
}
```

---

## 4. Search tool output schema (identical across all four servers, field names fixed)

```json
{
  "results": [
    {
      "content": "the passage text",
      "source": "document title",
      "section": "heading, if available",
      "score": 0.82,
      "chunk_id": "banking-doc-4:chunk-12"
    }
  ],
  "query": "the query as received",
  "total_found": 5
}
```

- `chunk_id` format: `<industry>-doc-<n>:chunk-<n>`
- `score`: float, higher is more relevant, normalized to 0-1 across all four servers
- `results` is always an array, empty or not

---

## 5. Empty result handling

A search that finds nothing returns a success response with an empty array, never an error, never a 404.

```json
{
  "results": [],
  "query": "refund policy for gift cards",
  "total_found": 0
}
```

---

## 6. Error shape (identical across all four servers)

```json
{
  "error": "invalid_parameter",
  "message": "top_k must be a positive integer",
  "retryable": false
}
```

Fixed fields: `error` (machine-readable code), `message` (human-readable), `retryable` (boolean).

---

## 7. Transport

Every server implements both:

```
MCP_TRANSPORT=stdio     (local dev/testing only)
MCP_TRANSPORT=http      (required for interop day and all demos)
```

Bind to your machine's actual network interface, not `localhost`.

### Server addresses (required, keep current)

| Intern | Industry | Host / IP | Port |
|---|---|---|---|
| 1 | Banking | | |
| 2 | Hospitality | | |
| 3 | Retail | 10.10.180.132 | 8003 |
| 4 | Telecom | | |

Update this table immediately if any address changes, other clients depend on it.

---

## 8. Resources and prompts (minimum requirement)

**One resource, minimum:**

```
kb_<industry>_documents   -> list of available document titles/IDs
```

**One prompt, minimum:**

```
kb_<industry>_<use_case>_template
```

Naming follows the same `kb_<industry>_<name>` pattern as tools.

---

## 9. Runtime discovery

No client may hardcode another server's tool, resource, or prompt names. All clients discover what a server exposes at connection time and adapt accordingly.

---

## 10. Sign-off

| Intern | Industry | Agreed |
|---|---|---|
| 1 | Banking | Yes |
| 2 | Hospitality | Yes |
| 3 | Retail | Yes |
| 4 | Telecom | Yes |
