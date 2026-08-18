"""Retail Relational Records Access Layer (Phase 2).

Provides deterministic, read-only semantic queries against `data/retail.db`.
Encapsulates all SQLite logic away from MCP server definitions.

Tools supported:
1. query_orders: Lookup order details and line items by order_id, customer_id, or brand.
2. query_shipments: Lookup carrier, tracking, delivery status, and package items.
3. query_returns: Lookup return requests, RMA codes, refund amounts, and statuses.
4. query_customer: Lookup customer profile and deterministic 2026 account aggregates.

Semantic Resource:
- get_retail_schema: Semantic documentation of the retail relational data model.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "retail.db"
REFERENCE_YEAR = "2026"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a configured SQLite connection with foreign keys and row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


class RetailRecords:
    """Data-access service for operational retail records."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    def _ensure_db(self) -> None:
        if not self.db_path.is_file():
            # Lazy initialize if not yet seeded
            from data.seed_records import seed_records
            seed_records(self.db_path)

    def query_orders(
        self,
        *,
        order_id: str | None = None,
        customer_id: str | None = None,
        brand: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Query orders with associated line items."""
        self._ensure_db()
        query_meta = {
            k: v for k, v in {
                "order_id": order_id,
                "customer_id": customer_id,
                "brand": brand,
                "limit": limit,
            }.items() if v is not None
        }

        conditions: list[str] = []
        params: list[Any] = []

        if order_id:
            conditions.append("o.order_id = ?")
            params.append(order_id.strip())
        if customer_id:
            conditions.append("o.customer_id = ?")
            params.append(customer_id.strip())
        if brand:
            conditions.append("o.brand = ?")
            params.append(brand.strip().lower())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT
                o.order_id, o.customer_id, o.brand, o.order_date,
                o.status, o.payment_status, o.subtotal, o.tax,
                o.shipping_cost, o.total_amount, o.currency,
                o.shipping_address, o.notes
            FROM orders o
            {where_clause}
            ORDER BY o.order_date DESC
            LIMIT ?;
        """
        params.append(max(1, min(limit, 50)))

        with get_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            order_rows = [dict(r) for r in cur.fetchall()]

            if not order_rows:
                return {"results": [], "total_found": 0, "query": query_meta}

            # Fetch line items for retrieved orders
            order_ids = [r["order_id"] for r in order_rows]
            placeholders = ",".join("?" for _ in order_ids)
            cur.execute(
                f"""
                SELECT
                    line_item_id, order_id, product_name, category,
                    sku, unit_price, quantity, total_price, status
                FROM line_items
                WHERE order_id IN ({placeholders})
                ORDER BY line_item_id ASC;
                """,
                order_ids,
            )
            items_by_order: dict[str, list[dict[str, Any]]] = {}
            for item in cur.fetchall():
                item_dict = dict(item)
                items_by_order.setdefault(item_dict["order_id"], []).append(item_dict)

            results: list[dict[str, Any]] = []
            for o in order_rows:
                o["line_items"] = items_by_order.get(o["order_id"], [])
                results.append(o)

            return {
                "results": results,
                "total_found": len(results),
                "query": query_meta,
            }

    def query_shipments(
        self,
        *,
        order_id: str | None = None,
        tracking_number: str | None = None,
        shipment_id: str | None = None,
    ) -> dict[str, Any]:
        """Query shipments and associated package line items."""
        self._ensure_db()
        query_meta = {
            k: v for k, v in {
                "order_id": order_id,
                "tracking_number": tracking_number,
                "shipment_id": shipment_id,
            }.items() if v is not None
        }

        conditions: list[str] = []
        params: list[Any] = []

        if order_id:
            conditions.append("s.order_id = ?")
            params.append(order_id.strip())
        if tracking_number:
            conditions.append("s.tracking_number = ?")
            params.append(tracking_number.strip())
        if shipment_id:
            conditions.append("s.shipment_id = ?")
            params.append(shipment_id.strip())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT
                s.shipment_id, s.order_id, s.tracking_number, s.carrier,
                s.ship_date, s.estimated_delivery, s.actual_delivery,
                s.status, s.item_ids_json
            FROM shipments s
            {where_clause}
            ORDER BY s.ship_date ASC;
        """

        with get_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            shipment_rows = [dict(r) for r in cur.fetchall()]

            if not shipment_rows:
                return {"results": [], "total_found": 0, "query": query_meta}

            # Map line items in packages
            results: list[dict[str, Any]] = []
            for s in shipment_rows:
                try:
                    item_ids = json.loads(s["item_ids_json"])
                except Exception:
                    item_ids = []
                s["item_ids"] = item_ids
                del s["item_ids_json"]

                if item_ids:
                    placeholders = ",".join("?" for _ in item_ids)
                    cur.execute(
                        f"SELECT line_item_id, product_name, category, status FROM line_items WHERE line_item_id IN ({placeholders});",
                        item_ids,
                    )
                    s["items"] = [dict(row) for row in cur.fetchall()]
                else:
                    s["items"] = []

                results.append(s)

            return {
                "results": results,
                "total_found": len(results),
                "query": query_meta,
            }

    def query_returns(
        self,
        *,
        customer_id: str | None = None,
        order_id: str | None = None,
        return_id: str | None = None,
        rma_code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Query returns with associated line item product details."""
        self._ensure_db()
        query_meta = {
            k: v for k, v in {
                "customer_id": customer_id,
                "order_id": order_id,
                "return_id": return_id,
                "rma_code": rma_code,
                "status": status,
            }.items() if v is not None
        }

        conditions: list[str] = []
        params: list[Any] = []

        if customer_id:
            conditions.append("r.customer_id = ?")
            params.append(customer_id.strip())
        if order_id:
            conditions.append("r.order_id = ?")
            params.append(order_id.strip())
        if return_id:
            conditions.append("r.return_id = ?")
            params.append(return_id.strip())
        if rma_code:
            conditions.append("r.rma_code = ?")
            params.append(rma_code.strip())
        if status:
            conditions.append("r.status = ?")
            params.append(status.strip().lower())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT
                r.return_id, r.order_id, r.line_item_id, r.customer_id,
                r.rma_code, r.request_date, r.reason, r.condition,
                r.status, r.refund_amount, r.refund_date, r.restocking_fee,
                li.product_name, li.category, o.brand
            FROM returns r
            LEFT JOIN line_items li ON r.line_item_id = li.line_item_id
            LEFT JOIN orders o ON r.order_id = o.order_id
            {where_clause}
            ORDER BY r.request_date DESC;
        """

        with get_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            results = [dict(r) for r in cur.fetchall()]
            return {
                "results": results,
                "total_found": len(results),
                "query": query_meta,
            }

    def query_customer(
        self,
        *,
        customer_id: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Query customer profile and deterministic operational aggregates."""
        self._ensure_db()
        query_meta = {
            k: v for k, v in {
                "customer_id": customer_id,
                "email": email,
            }.items() if v is not None
        }

        if not customer_id and not email:
            return {"results": [], "total_found": 0, "query": query_meta, "error": "Must provide customer_id or email"}

        conditions: list[str] = []
        params: list[Any] = []
        if customer_id:
            conditions.append("c.customer_id = ?")
            params.append(customer_id.strip())
        if email:
            conditions.append("c.email = ?")
            params.append(email.strip().lower())

        where_clause = f"WHERE {' AND '.join(conditions)}"
        sql = f"""
            SELECT customer_id, name, email, phone, created_at, status
            FROM customers c
            {where_clause};
        """

        with get_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            cust_rows = [dict(r) for r in cur.fetchall()]

            if not cust_rows:
                return {"results": [], "total_found": 0, "query": query_meta}

            results: list[dict[str, Any]] = []
            for cust in cust_rows:
                cid = cust["customer_id"]

                # 1. Total orders in reference year (2026)
                cur.execute(
                    "SELECT COUNT(*) AS order_count, COALESCE(SUM(total_amount), 0.0) AS total_spent FROM orders WHERE customer_id = ? AND strftime('%Y', order_date) = ?;",
                    (cid, REFERENCE_YEAR),
                )
                order_agg = cur.fetchone()

                # 2. Completed refunds in reference year (2026)
                cur.execute(
                    "SELECT COALESCE(SUM(refund_amount), 0.0) AS total_refunded FROM returns WHERE customer_id = ? AND status = 'completed' AND strftime('%Y', refund_date) = ?;",
                    (cid, REFERENCE_YEAR),
                )
                completed_refund_agg = cur.fetchone()

                # 3. Open / in-process returns
                cur.execute(
                    """
                    SELECT COUNT(*) AS open_count, COALESCE(SUM(refund_amount), 0.0) AS pending_amount
                    FROM returns
                    WHERE customer_id = ? AND status IN ('requested', 'approved', 'label_generated', 'in_transit', 'received', 'inspecting', 'refund_processing');
                    """,
                    (cid,),
                )
                open_returns_agg = cur.fetchone()

                # 4. Recent order list summary
                cur.execute(
                    "SELECT order_id, brand, order_date, status, payment_status, total_amount FROM orders WHERE customer_id = ? ORDER BY order_date DESC LIMIT 5;",
                    (cid,),
                )
                recent_orders = [dict(r) for r in cur.fetchall()]

                cust["aggregates_2026"] = {
                    "orders_placed_count": order_agg["order_count"],
                    "total_spent": round(order_agg["total_spent"], 2),
                    "total_refunded_completed": round(completed_refund_agg["total_refunded"], 2),
                    "open_returns_count": open_returns_agg["open_count"],
                    "pending_refund_amount": round(open_returns_agg["pending_amount"], 2),
                }
                cust["recent_orders"] = recent_orders
                results.append(cust)

            return {
                "results": results,
                "total_found": len(results),
                "query": query_meta,
            }


def get_retail_schema() -> dict[str, Any]:
    """Return the semantic schema description for the kb://retail/schema resource."""
    return {
        "resource": "kb://retail/schema",
        "description": "Semantic data model for retail operational records (orders, line items, shipments, returns, customers).",
        "version": "1.0",
        "tables": {
            "customers": {
                "description": "Customer accounts and contact information.",
                "primary_key": "customer_id",
                "fields": {
                    "customer_id": "Unique customer identifier (e.g. 'CUST-101')",
                    "name": "Customer full name",
                    "email": "Customer email address",
                    "phone": "Contact telephone number",
                    "created_at": "Account creation timestamp (ISO 8601)",
                    "status": "Account status: 'active', 'suspended', 'closed'"
                }
            },
            "orders": {
                "description": "Placed e-commerce orders across retail brands (Amazon, Best Buy, IKEA, Target).",
                "primary_key": "order_id",
                "foreign_keys": {"customer_id": "customers.customer_id"},
                "fields": {
                    "order_id": "Unique order reference (e.g. 'ORD-9011')",
                    "customer_id": "Reference to purchasing customer",
                    "brand": "Retail brand: 'amazon', 'bestbuy', 'ikea', 'target'",
                    "order_date": "Date order was placed (YYYY-MM-DD)",
                    "status": "Order fulfillment status: 'pending', 'processing', 'shipped', 'partially_shipped', 'delivered', 'cancelled', 'auth_hold'",
                    "payment_status": "Payment state: 'authorized' (hold only), 'captured' (settled charge), 'refunded', 'partially_refunded', 'voided'",
                    "total_amount": "Total order charge including tax and shipping (USD)",
                    "notes": "Operational notes (e.g. duplicate authorization hold details, split shipment reasons)"
                }
            },
            "line_items": {
                "description": "Individual items contained within an order.",
                "primary_key": "line_item_id",
                "foreign_keys": {"order_id": "orders.order_id"},
                "fields": {
                    "line_item_id": "Unique item reference (e.g. 'ITEM-9011-1')",
                    "order_id": "Parent order reference",
                    "product_name": "Product title/description",
                    "category": "Merchandise category: 'electronics', 'appliances', 'furniture', 'storage', 'home'",
                    "sku": "Stock keeping unit",
                    "unit_price": "Price per single unit (USD)",
                    "quantity": "Purchased quantity",
                    "total_price": "Total line price (USD)",
                    "status": "Item delivery state: 'pending', 'shipped', 'delivered', 'returned', 'cancelled'"
                }
            },
            "shipments": {
                "description": "Fulfillment packages and tracking information. Supports split orders where items ship separately.",
                "primary_key": "shipment_id",
                "foreign_keys": {"order_id": "orders.order_id"},
                "fields": {
                    "shipment_id": "Unique package shipment reference (e.g. 'SHIP-401')",
                    "order_id": "Associated order reference",
                    "tracking_number": "Carrier tracking number",
                    "carrier": "Shipping carrier (e.g. 'USPS', 'UPS', 'FedEx', 'Amazon Logistics')",
                    "ship_date": "Date package was dispatched",
                    "estimated_delivery": "Estimated arrival date",
                    "actual_delivery": "Actual delivery date (null if in-transit)",
                    "status": "Package state: 'label_created', 'in_transit', 'out_for_delivery', 'delivered', 'failed_attempt', 'returned_to_sender'",
                    "item_ids": "List of line_item_id references packed in this shipment"
                }
            },
            "returns": {
                "description": "Return requests, RMA codes, refund tracking, and merchandise inspection states.",
                "primary_key": "return_id",
                "foreign_keys": {
                    "order_id": "orders.order_id",
                    "line_item_id": "line_items.line_item_id",
                    "customer_id": "customers.customer_id"
                },
                "fields": {
                    "return_id": "Unique return reference (e.g. 'RET-701')",
                    "order_id": "Associated order reference",
                    "line_item_id": "Specific returned item reference",
                    "customer_id": "Customer who requested return",
                    "rma_code": "Return Merchandise Authorization code (e.g. 'RMA-AMZ-701-9031')",
                    "request_date": "Date return was submitted",
                    "reason": "Reason for return: 'damaged', 'defective', 'wrong_item', 'unwanted', 'not_as_described', 'late_delivery'",
                    "condition": "Item condition: 'unopened', 'opened_unused', 'used', 'damaged'",
                    "status": "Return processing state: 'requested', 'approved', 'label_generated', 'in_transit', 'received', 'inspecting', 'refund_processing', 'completed', 'rejected'",
                    "refund_amount": "Refund amount in USD",
                    "refund_date": "Date refund was issued to payment method (null if pending)",
                    "restocking_fee": "Restocking fee deducted if applicable (e.g. Best Buy activatable devices)"
                }
            }
        },
        "supported_tools": [
            "kb_retail_query_orders",
            "kb_retail_query_shipments",
            "kb_retail_query_returns",
            "kb_retail_query_customer"
        ]
    }
