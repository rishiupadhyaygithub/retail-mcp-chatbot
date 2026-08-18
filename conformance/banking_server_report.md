# Interop Conformance Report: Banking MCP Server

**Tester:** Rishi Upadhyay (Retail Domain)  
**Target Server:** Banking MCP Server (Aseem)  
**Endpoint:** `http://10.10.180.175:8420/mcp`  
**Transport:** Streamable HTTP (`/mcp`)  
**Date Tested:** 18 August 2026  
**Status:** **CONFORMANT (PASS)**

---

## 1. Protocol & Capability Discovery

| Check | Expected Behavior | Observed Result | Status |
|---|---|---|---|
| **Endpoint Reachability** | Responds on `http://10.10.180.175:8420/mcp` | 200 OK on SSE handshake / JSON-RPC session | **PASS** |
| **Tool Discovery (`tools/list`)** | Advertises `kb_banking_search` with typed schema | Advertises `banking__kb_banking_search` with `query` (str) and `top_k` (int) | **PASS** |
| **Runtime Negotiation** | Client discovers tools dynamically without hardcoding | Successfully dynamically discovered into `MCPFleet` | **PASS** |

---

## 2. Functional Tool Execution

### A. Direct Banking Query
* **Query:** `"What is KeyBank policy for unlocking an account online?"`
* **Response Payload:** Returned relevant passages from `"KeyBank - Locked out of Online and Mobile Banking"`, including online recovery tool and `1-800-KEY2YOU` phone verification.
* **Latency:** < 120ms network protocol roundtrip.
* **Status:** **PASS**

### B. Dispute Investigation Query
* **Query:** `"How do I dispute an unauthorized transaction on my card?"`
* **Response Payload:** Returned structured steps from `"U.S. Bank - How do I dispute a transaction on my card?"`.
* **Status:** **PASS**

---

## 3. Cross-Server Synthesis (Retail + Banking)

* **Cross-Domain Prompt:** `"Compare the policy on Amazon refund timelines with how banks handle credit card transaction disputes."`
* **Execution:**
  1. Client called `retail__kb_retail_search` on `:8003` (retrieved Amazon 30d refund policy).
  2. Client called `banking__kb_banking_search` on `:8420` (retrieved Bank of America 60d dispute window).
  3. LLM synthesized a unified comparative answer citing both `[retail: Amazon — Refund Timelines]` and `[banking: Bank of America - Credit Card Dispute FAQ]`.
* **Status:** **PASS**

---

## 4. Summary & Verdict

The Banking MCP Server meets all contract v1/v2 requirements for Streamable HTTP transport, JSON-RPC schema conformance, and vector retrieval accuracy.
