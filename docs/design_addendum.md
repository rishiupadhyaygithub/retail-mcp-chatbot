# TOPAZ Retail MCP Assistant — Design Addendum (Phases 2 & 3)

**Author:** Rishi Upadhyay  
**Date:** 18 August 2026  
**Status:** Approved & Implemented  
**Scope:** Phase 2 (Structured Operational Records) & Phase 3 (State-Changing Action & Safety Gates)

---

## 1. Relational Schema Architecture

The relational operational dataset is implemented in SQLite at `data/retail.db` and initialized via `data/schema.sql` and `data/seed_records.py`.

### A. Tables & Entity Relationships
The schema models 5 interconnected entities in Third Normal Form (3NF) with strict foreign key constraints:

1. **`customers` (3 rows):** Core customer accounts (`customer_id` PK, `name`, `email`, `phone`, `created_at`, `status`).
2. **`orders` (6 rows):** Multi-retailer purchase transactions (`order_id` PK, `customer_id` FK, `brand`, `order_date`, `status`, `payment_status`, `subtotal`, `tax`, `shipping_cost`, `total_amount`, `currency`, `shipping_address`, `notes`).
3. **`line_items` (8 rows):** Individual items inside an order (`line_item_id` PK, `order_id` FK, `product_name`, `category`, `sku`, `unit_price`, `quantity`, `total_price`, `status`).
4. **`shipments` (5 rows):** Parcel logistics packages (`shipment_id` PK, `order_id` FK, `tracking_number`, `carrier`, `ship_date`, `estimated_delivery`, `actual_delivery`, `status`, `item_ids_json`). Supports split multi-package shipments.
5. **`returns` (3 rows):** Historical and created return authorizations (`return_id` PK, `order_id` FK, `customer_id` FK, `line_item_id` FK, `rma_code`, `reason`, `condition`, `refund_amount`, `status`, `created_at`, `idempotency_key`).
6. **`return_sequences` (1 row):** Concurrency-safe atomic counter for incremental sequence generation.

### B. Seed Generation & Evaluation Scenarios
Data generation is 100% deterministic relative to reference date `2026-08-18`:
* **Duplicate Charge (Q14):** Alex Rivera (`CUST-101`) has `ORD-9011` ($129.99 captured) and `ORD-9012` ($129.99 authorized hold).
* **Split Shipment (Q8, Q9, Q16):** Sarah Chen (`CUST-102`) order `ORD-9021` split into `SHIP-402` (FedEx, delivered) and `SHIP-403` (UPS, in transit).
* **Return Window Eligibility (Q15):** Marcus Vance (`CUST-103`) has `ORD-9031` placed 12 days ago (eligible under Amazon 30d window) vs `ORD-9032` placed 48 days ago (ineligible under Best Buy 15d window).
* **Duplicate Return Attempt (Q25):** `ORD-9033` item `ITEM-9033-1` has existing return `RET-702` (completed), enforcing loud refusal.

---

## 2. Query Tool Schemas (Phase 2)

All query tools are exposed over Streamable HTTP FastMCP (`server/main.py`) with data access encapsulated in `server/records.py`.

### A. Parameterized Tools
1. **`kb_retail_query_orders`:**
   * Parameters: `order_id` (string), `customer_id` (string), `brand` (string), `status` (string), `from_date` (string), `to_date` (string), `limit` (int, default 10, max 50).
   * Invariants: Returns matching order headers and nested `line_items` arrays.
2. **`kb_retail_query_shipments`:**
   * Parameters: `order_id` (string), `tracking_number` (string), `shipment_id` (string).
   * Invariants: Returns carrier tracking, dispatch/delivery timestamps, status, and package items.
3. **`kb_retail_query_returns`:**
   * Parameters: `customer_id` (string), `order_id` (string), `return_id` (string), `rma_code` (string), `status` (string).
   * Invariants: Returns RMA codes, inspection status, and refund progress.
4. **`kb_retail_query_customer`:**
   * Parameters: `customer_id` (string, required).
   * Invariants: Computes exact 2026 aggregates (`orders_placed_count`, `total_spent`, `total_refunded_completed`, `open_returns_count`, `pending_refund_amount`).

### B. Result Envelopes & Empty Honesty
When zero rows match, query tools return:
```json
{
  "results": [],
  "total_found": 0,
  "query": { "order_id": "ORD-9999" }
}
```
This gives the client an unambiguous signal to report an honest refusal rather than hallucinate.

---

## 3. Action Tool Schema & State Mutation (Phase 3)

The state-changing action is implemented as `kb_retail_create_return`.

### A. Parameters & Contract
* **Required Parameters:** `order_id` (string), `line_item_id` (string), `reason` (string).
* **Optional Parameters:** `customer_id` (string), `condition` (string, default "opened"), `idempotency_key` (string).
* **Return Shape:**
```json
{
  "return_id": "RET-704",
  "rma_code": "RMA-AMZ-704-9011",
  "order_id": "ORD-9011",
  "line_item_id": "ITEM-9011-1",
  "customer_id": "CUST-101",
  "refund_amount": 119.99,
  "status": "requested",
  "created_at": "2026-08-18"
}
```

### B. Eight Pre-Flight Validation Gates
The server executes atomic database writes only after validating:
1. `order_id`, `line_item_id`, and `reason` are non-empty strings.
2. `order_id` exists in `orders`.
3. `line_item_id` belongs to the specified `order_id`.
4. If `customer_id` is supplied, it matches `orders.customer_id`.
5. Order status is `delivered` (cannot return unfulfilled items).
6. Idempotent replay detection: Identical `idempotency_key` returns existing record with `idempotent_replay: true`.
7. Duplicate return prevention: If `line_items.status == 'returned'`, rejects loudly with `item_already_returned`.
8. Concurrency-safe atomic transaction: Increments `return_sequences`, inserts into `returns`, and updates `line_items.status = 'returned'`.

---

## 4. Human-in-the-Loop Confirmation Flow

The LLM is strictly prohibited from executing state mutations without explicit user consent.

```
[User Request: "Return ORD-9011"]
             │
             ▼
   [Read-Only Investigation]
  (query_orders + kb_retail_search)
             │
             ▼
 [WAITING_FOR_CONFIRMATION State]
  (Display Proposal & Refund Amount)
             │
      ┌──────┴──────┐
      ▼             ▼
[User Confirms]  [User Cancels]
      │             │
      ▼             ▼
[Execute Action]  [Abort Flow]
(kb_retail_create_return) (0 Mutations)
```

1. **Investigation Phase:** Client fetches order details, checks return window policy in Chroma, and calculates estimated refund. Zero writes occur.
2. **Proposal Phase:** Assistant formats a proposal with exact fields (`order_id`, `line_item_id`, `product_name`, `refund_amount`, `reason`) and prompts for confirmation.
3. **Execution Phase:** Only when user responds affirmatively (`"Yes, confirm"`, `"Proceed"`, or clicks UI button) does the client invoke `kb_retail_create_return`.

---

## 5. Context Budgeting & Token Management

To prevent local model context exhaustion (4096 / 8192 token limit on `qwen2.5:7b-instruct` / `qwen3:8b`):
1. **Columnar Result Formatting:** Tool payloads use clean field projections, omitting internal SQLite rowids and intermediate flags.
2. **Top-K Truncation:** Semantic search caps at `top_k=5` (~1200 tokens). Query tools default to `limit=10`.
3. **Rolling Conversational Window:** The client UI maintains a sliding 10-message window, dropping stale historical turns while preserving the active session context.

---

## 6. Prompt Formatting & Provenance Citations

Every claim made by the assistant is grounded and cited:
* **Unstructured Policy:** Cited as `[retail: <Document Title>]` or `[banking: <Document Title>]`.
* **Structured Records:** Cited with specific entity IDs (e.g. `[retail: order ORD-9011, shipment SHIP-402]`).

---

## 7. Lessons from Phase 1 & Architectural Takeaways

1. **Separate Data from Reasoning:** MCP servers must remain pure deterministic data pipes. Reasoning belongs entirely in the client orchestrator.
2. **Structured Records != RAG:** Relational facts must be queried with parameterized SQL tools, not vector search.
3. **Defensive Concurrency:** Concurrency-safe ID generation requires atomic sequence counters inside `BEGIN IMMEDIATE` transactions.
