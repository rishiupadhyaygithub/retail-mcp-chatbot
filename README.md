# TOPAZ Retail MCP Server + Multi-Server Chatbot Assistant

An enterprise-grade **Model Context Protocol (MCP)** server for the **Retail** industry, paired with an intelligent **contact-center orchestrator and web interface** that connects to multi-domain MCP servers (Retail, Banking, Hospitality, Telecom).

> **Core Architectural Invariant:** The MCP server handles deterministic data retrieval, SQL queries, and transactional writes and **never calls a chat LLM**. The client orchestrator handles reasoning, multi-turn state tracking, tool selection, human safety confirmation gates, and synthesized text generation.

---

## 1. Architecture Overview

```
                      ┌─────────────────────────────────────────────────────────┐
                      │                   DATA STORAGE LAYER                    │
                      │   Unstructured (ChromaDB)   +   Structured (SQLite DB)  │
                      └───────────────────────────┬─────────────────────────────┘
                                                  │
                      ┌───────────────────────────▼─────────────────────────────┐
                      │                    MCP SERVER LAYER                     │
                      │  Retail Server (:8003/mcp)  |  Banking (:8420)  |  ...  │
                      │  Tools: search, query_orders, shipments, create_return  │
                      └───────────────────────────┬─────────────────────────────┘
                                                  │ (Streamable HTTP /mcp)
                      ┌───────────────────────────▼─────────────────────────────┐
                      │                MCP FLEET / ROUTER LAYER                 │
                      │      Parallel Discovery & Graceful Degradation          │
                      │             (client/mcp_client.py: MCPFleet)            │
                      └───────────────────────────┬─────────────────────────────┘
                                                  │
                      ┌───────────────────────────▼─────────────────────────────┐
                      │             ORCHESTRATOR & LLM CHAT ENGINE              │
                      │  - External LLM (vLLM on GB10, OpenAI-compatible)       │
                      │  - Dual-Provenance Synthesis (client/composite.py)      │
                      │  - Conversational State Machine (client/workflow.py)    │
                      │  - Action Confirmation Safety Gates (client/loop.py)    │
                      └───────────────────────────┬─────────────────────────────┘
                                                  │ (REST API /api/chat)
                      ┌───────────────────────────▼─────────────────────────────┐
                      │               AGENT WEB UI (FRONTEND)                   │
                      │         http://localhost:8080 (client/app.py)           │
                      └─────────────────────────────────────────────────────────┘
```

---

## 2. Repository Layout

| Path | Contents & Description |
|---|---|
| **`server/`** | FastMCP server implementation (`main.py`), SQLite data access layer (`records.py`), and Chroma retrieval (`retrieval.py`). Exposes 6 tools and 2 resources. |
| **`client/`** | MCP client fleet (`mcp_client.py`), LLM tool-calling loop (`loop.py`), multi-turn workflow state machine (`workflow.py`), composite reasoner (`composite.py`), web server (`app.py`), and frontend SPA (`ui/index.html`). |
| **`data/`** | Policy corpus (22 markdown docs across Amazon, Best Buy, Target, IKEA), ingestion scripts (`ingest.py`), SQLite schema (`schema.sql`), and deterministic dataset seeder (`seed_records.py`). |
| **`docs/`** | Main design document (`design_document.md`), Phase 2/3 design addendum (`design_addendum.md`), and architecture references. |
| **`eval/`** | Ground truth dataset (`ground_truth.json`), 28 evaluation benchmark questions (`eval_set.md`), and automated evaluation harness (`harness.py`). |
| **`conformance/`** | Interop conformance reports on teammate servers (`banking_server_report.md`). |
| **`prompts/`** | Versioned system prompts (`system_prompt_v1.md`, `system_prompt_v2.md`). |
| **`contract/`** | Shared interface agreements (`contract_v1.md`, `vector_db_contract.md`). |
| **`tests/`** | Complete 48-test pytest verification suite across unit, integration, protocol, concurrency, and safety gates. |
| **`scripts/`** | End-to-end product audit script (`e2e_demo_audit.py`) and `verify_all.py`, the single command that checks every path a change can break. |

---

## 3. The Three Implementation Phases

### Phase 1: Unstructured Knowledge Retrieval (RAG)
* **Corpus & Chunking:** 22 markdown files chunked via heading and packed strategies.
* **Vector Store:** ChromaDB running on port `8100` with dense `BAAI/bge-m3` 1024-d embeddings.
* **Tool:** `kb_retail_search(query, top_k)` returning relevance-scored passages with document source and section metadata.
* **Performance:** 100% Recall@5, 100% Recall@1 on heading strategy.

### Phase 2: Structured Operational Records
* **Relational Schema:** 5 normalized tables in SQLite (`customers`, `orders`, `line_items`, `shipments`, `returns`) seeded deterministically.
* **Parameterized Tools:**
  * `kb_retail_query_orders`: Order lookup by ID, customer, brand, status, or date range.
  * `kb_retail_query_shipments`: Carrier tracking, delivery timestamps, and split-shipment packages.
  * `kb_retail_query_returns`: RMA tracking, return reasons, condition, and refund status.
  * `kb_retail_query_customer`: Customer profile and 2026 financial summary aggregates.
* **Composite Reasoning:** `CompositeReasoner` synthesizes SQLite operational state with Chroma policy rules (e.g. Q15 return eligibility, Q14 duplicate charges vs auth holds).

### Phase 3: State-Changing Actions & Safety Gates
* **Action Tool:** `kb_retail_create_return(order_id, line_item_id, reason, customer_id, condition)` returning atomic RMA codes (`RMA-AMZ-704-9011`).
* **Safety Invariants:**
  * **Zero Unattended Writes:** The LLM can never write to SQLite without human confirmation.
  * **8 Pre-Flight Validation Gates:** Enforces order existence, item linkage, customer matching, delivered fulfillment status, duplicate return prevention, and idempotent replay.
  * **Concurrency-Safe Sequence Generation:** Atomic sequence table (`return_sequences`) inside `BEGIN IMMEDIATE` transactions.
  * **Honest Missing-Field Clarification:** Missing parameters prompt the user without hallucinating (Q23).

---

## 4. Quickstart & Local Execution

### 1. Prerequisites & Environment
```bash
# Python 3.10+
pip install -r requirements.txt
pip install -r client/requirements.txt
```

### 2. Start Services

#### A. Start ChromaDB Vector Store (Port 8100)
```bash
chroma run --host 0.0.0.0 --port 8100 --path data/chroma &
```

#### B. Seed SQLite Database & Ingest Corpus
```bash
# Ingest document corpus:
python3 data/ingest.py --strategy heading --rebuild

# Seed relational database:
python3 data/seed_records.py
```

#### C. Start Retail MCP Server (Port 8003)
```bash
# Streamable HTTP transport at /mcp:
python3 server/main.py --transport http --host 0.0.0.0 --port 8003 &
```

#### D. Start Contact-Center Chat Web UI (Port 8080)
```bash
python3 client/app.py --host 0.0.0.0 --port 8080 &
```

Open your browser at:
👉 **[http://localhost:8080](http://localhost:8080)**

---

## 5. Live Product Journeys & CLI Audit

You can execute all 7 end-to-end user journeys in the terminal in one command:

```bash
python3 scripts/e2e_demo_audit.py
```

### Verified User Journeys Tested:
1. **Policy-Only Question:** *"Can a customer return opened electronics at Best Buy?"* → Cites `[retail: Best Buy — Return & Exchange Policy]`.
2. **Record-Only Operational Lookup:** *"Look up order ORD-9011"* → Returns order status, line items, and amount from SQLite.
3. **Composite Synthesis (Dual Provenance):** *"Can they return order ORD-9031 — what's the window and is it eligible?"* → Combines order date (12 days ago) + Amazon policy (30d window) to deduce eligibility.
4. **State-Changing Return Creation with Safety Confirmation:** Proposes return with refund amount → User clicks **[Confirm]** → Generates RMA code `RMA-AMZ-703-9011`.
5. **Ambiguous/Missing Parameters (Q23):** *"start a return for this customer"* → Prompts user for order ID and item ID without guessing.
6. **Duplicate Return Prevention (Q25):** *"open a return on ORD-9033 for item ITEM-9033-1"* → Refuses duplicate return for already-returned item (`RET-702`).
7. **Honest Refusal on Unknown Records (Q28):** *"status of order ORD-99999999?"* → Honestly reports order not found.

---

## 6. Multi-Server Interoperability (Banking Partner Integration)

The client fleet dynamically discovers and connects to partner MCP servers configured in `client/servers.json`:

* **Retail MCP Server:** `http://127.0.0.1:8003/mcp` (Active)
* **Banking MCP Server (Aseem):** `http://10.10.180.175:8420/mcp` (Active)

### Cross-Server Comparative Prompts (Tested Live):
> *"Compare the policy on Amazon refund timelines with how U.S. Bank handles card transaction disputes."*
* Calls `retail.kb_retail_search` + `banking.kb_banking_search` in parallel.
* Synthesizes a unified comparative response citing both `[retail: Amazon — Refund Timelines]` and `[banking: Bank of America - Credit Card Dispute FAQ]`.

---

## 7. Automated Test Suite

**Run everything with one command** — not only the tests, but every path a
change can break, including cross-file consistency and the claims this README
makes about itself:

```bash
python3 scripts/verify_all.py
```

Add `--slow` to include the retrieval harness (needs Chroma running). This
exists because editing for one entry point does not exercise the others: a
`schema_version` bump once left `eval/harness.py` refusing to start, and it was
found by accident rather than by a check. Anything verified by a command typed
once is unverified from the next commit onward.

The pytest suite alone:

```bash
python3 -m pytest tests/ -v
```

**Results:** **89 of 89 passed (100%)** in ~21s.

| File | Covers | Tests |
|---|---|---|
| `test_client_gates.py` | Client gates and helpers: composite/comparative detection, brand extraction, schema-driven argument discovery, unreachable-server diagnostics, passage flattening | 41 |
| `test_action_create_return.py` | Validation gates, idempotency, rollbacks, RMA generation | 9 |
| `test_records.py` | SQLite queries and aggregates | 8 |
| `test_mcp_server.py` | Contract payloads, parameter validation, error shapes | 7 |
| `test_composite_reasoning.py` | Dual-provenance reasoning across Q14–Q17 | 6 |
| `test_conversational_workflow.py` | Multi-turn state machine, confirmation gates, context resolution | 6 |
| `test_mcp_records.py` | FastMCP tool and resource discovery | 5 |
| `test_records_db.py` | Schema and foreign-key integrity | 3 |
| `test_transport.py` | Streamable HTTP over a real socket | 2 |
| `test_retrieval.py` | Vector search | 1 |
| `test_contract.py` | Contract v1 payload shape | 1 |
