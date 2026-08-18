#!/usr/bin/env python3
"""Deterministic seed data generator for Retail Relational Store (Phase 2).

Populates `data/retail.db` with deterministic fixtures derived directly from
the evaluation requirements in `eval/eval_set.md` (Questions 8-17, 28).

Evaluation Reference Date: 2026-08-18

Scenarios Seeded:
1. CUST-101 (Alex Rivera): Duplicate Charge vs Temporary Auth Hold (Q11, Q14)
   - ORD-9011: Captured $129.99 (Kindle Paperwhite, delivered)
   - ORD-9012: Auth Hold $129.99 (Pending duplicate release, not captured)
2. CUST-102 (Sarah Chen): Split Shipment & Partial Delivery (Q8, Q9, Q13, Q16)
   - ORD-9021: Partially shipped (Target order)
     - ITEM-9021-1 (Ninja Blender): Delivered via SHIP-402
     - ITEM-9021-2 (Brita Filter): In Transit via SHIP-403
3. CUST-103 (Marcus Vance): Return Eligibility & Refund Timelines (Q10, Q12, Q15, Q17)
   - ORD-9031: Placed 2026-08-06 (12d ago) -> Inside Amazon 30d window (ELIGIBLE)
     - RET-701: Status 'refund_processing' for $89.50 (Open return)
   - ORD-9032: Placed 2026-07-01 (48d ago) -> Outside Best Buy 15d window (INELIGIBLE)
   - ORD-9033: Placed 2026-05-10 (IKEA order) -> RET-702 completed ($60.48 refunded)
4. Non-existent entities (e.g. ORD-99999999) -> Query returns empty result (Q28)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "retail.db"
SCHEMA_PATH = REPO_ROOT / "data" / "schema.sql"

REFERENCE_DATE = "2026-08-18"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = schema_path.read_text(encoding="utf-8")
    with get_connection(db_path) as conn:
        # Drop existing tables in reverse dependency order for clean idempotent rebuild
        conn.executescript("""
            PRAGMA foreign_keys = OFF;
            DROP TABLE IF EXISTS returns;
            DROP TABLE IF EXISTS shipments;
            DROP TABLE IF EXISTS line_items;
            DROP TABLE IF EXISTS orders;
            DROP TABLE IF EXISTS customers;
            PRAGMA foreign_keys = ON;
        """)
        conn.executescript(schema_sql)


def seed_records(db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # ==========================================
        # 1. CUSTOMERS
        # ==========================================
        customers = [
            ("CUST-101", "Alex Rivera", "alex.rivera@example.com", "+1-555-0101", "2026-01-10", "active"),
            ("CUST-102", "Sarah Chen", "sarah.chen@example.com", "+1-555-0102", "2026-02-15", "active"),
            ("CUST-103", "Marcus Vance", "marcus.vance@example.com", "+1-555-0103", "2026-03-01", "active"),
        ]
        cur.executemany(
            "INSERT INTO customers (customer_id, name, email, phone, created_at, status) VALUES (?, ?, ?, ?, ?, ?);",
            customers,
        )

        # ==========================================
        # 2. ORDERS
        # ==========================================
        orders = [
            # CUST-101: Duplicate charge scenario (ORD-9011 captured, ORD-9012 auth hold)
            (
                "ORD-9011", "CUST-101", "amazon", "2026-08-10", "delivered", "captured",
                119.99, 10.00, 0.00, 129.99, "USD", "742 Evergreen Terrace, Springfield, OR 97477",
                "Primary settled transaction for Kindle Paperwhite"
            ),
            (
                "ORD-9012", "CUST-101", "amazon", "2026-08-10", "auth_hold", "authorized",
                119.99, 10.00, 0.00, 129.99, "USD", "742 Evergreen Terrace, Springfield, OR 97477",
                "Duplicate authorization hold pending release by bank within 5-7 business days; not captured."
            ),
            # CUST-102: Split shipment scenario
            (
                "ORD-9021", "CUST-102", "target", "2026-08-11", "partially_shipped", "captured",
                79.98, 5.51, 0.00, 85.49, "USD", "10880 Wilshire Blvd, Los Angeles, CA 90024",
                "Order split into two separate packages due to warehouse availability."
            ),
            # CUST-103: Eligible vs Ineligible returns + completed refund
            (
                "ORD-9031", "CUST-103", "amazon", "2026-08-06", "delivered", "captured",
                79.99, 9.51, 0.00, 89.50, "USD", "221B Baker St, Marylebone, London / New York, NY 10001",
                "Amazon order placed 12 days before reference date 2026-08-18 (inside 30d window: ELIGIBLE)."
            ),
            (
                "ORD-9032", "CUST-103", "bestbuy", "2026-07-01", "delivered", "captured",
                229.99, 20.00, 0.00, 249.99, "USD", "221B Baker St, Marylebone, London / New York, NY 10001",
                "Best Buy order placed 48 days before reference date 2026-08-18 (outside 15d window: INELIGIBLE)."
            ),
            (
                "ORD-9033", "CUST-103", "ikea", "2026-05-10", "delivered", "partially_refunded",
                100.48, 10.00, 0.00, 110.48, "USD", "221B Baker St, Marylebone, London / New York, NY 10001",
                "IKEA order with past completed return for KALLAX unit."
            ),
        ]
        cur.executemany(
            """INSERT INTO orders (
                order_id, customer_id, brand, order_date, status, payment_status,
                subtotal, tax, shipping_cost, total_amount, currency, shipping_address, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            orders,
        )

        # ==========================================
        # 3. LINE ITEMS
        # ==========================================
        line_items = [
            # ORD-9011 & ORD-9012
            ("ITEM-9011-1", "ORD-9011", "Kindle Paperwhite (16 GB)", "electronics", "AMZ-KND-16", 119.99, 1, 119.99, "delivered"),
            ("ITEM-9012-1", "ORD-9012", "Kindle Paperwhite (16 GB) - Pending Hold", "electronics", "AMZ-KND-16", 119.99, 1, 119.99, "pending"),
            # ORD-9021 (Split items)
            ("ITEM-9021-1", "ORD-9021", "Ninja Personal Blender", "appliances", "TGT-NJA-BLD", 49.99, 1, 49.99, "delivered"),
            ("ITEM-9021-2", "ORD-9021", "Brita Water Filter Pitcher (6 Cup)", "home", "TGT-BRT-6C", 29.99, 1, 29.99, "shipped"),
            # ORD-9031, ORD-9032, ORD-9033
            ("ITEM-9031-1", "ORD-9031", "Sony WH-CH520 Wireless Headphones", "electronics", "AMZ-SNY-WH", 79.99, 1, 79.99, "delivered"),
            ("ITEM-9032-1", "ORD-9032", "Bose SoundLink Flex Bluetooth Speaker", "electronics", "BBY-BOS-FLX", 229.99, 1, 229.99, "delivered"),
            ("ITEM-9033-1", "ORD-9033", "KALLAX Shelf Unit (White)", "furniture", "IKA-KLX-WHT", 55.48, 1, 55.48, "returned"),
            ("ITEM-9033-2", "ORD-9033", "DRÖNA Storage Box (Dark Grey)", "storage", "IKA-DRN-DGY", 45.00, 1, 45.00, "delivered"),
        ]
        cur.executemany(
            """INSERT INTO line_items (
                line_item_id, order_id, product_name, category, sku,
                unit_price, quantity, total_price, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            line_items,
        )

        # ==========================================
        # 4. SHIPMENTS
        # ==========================================
        shipments = [
            (
                "SHIP-401", "ORD-9011", "TBA901111223344", "Amazon Logistics",
                "2026-08-10", "2026-08-12", "2026-08-12", "delivered",
                json.dumps(["ITEM-9011-1"])
            ),
            # Split shipments for ORD-9021
            (
                "SHIP-402", "ORD-9021", "94001118992233445501", "USPS",
                "2026-08-12", "2026-08-14", "2026-08-14", "delivered",
                json.dumps(["ITEM-9021-1"])
            ),
            (
                "SHIP-403", "ORD-9021", "94001118992233445502", "USPS",
                "2026-08-16", "2026-08-19", None, "in_transit",
                json.dumps(["ITEM-9021-2"])
            ),
            # CUST-103 Shipments
            (
                "SHIP-404", "ORD-9031", "TBA903133445566", "Amazon Logistics",
                "2026-08-06", "2026-08-08", "2026-08-08", "delivered",
                json.dumps(["ITEM-9031-1"])
            ),
            (
                "SHIP-405", "ORD-9032", "1Z999AA10123456784", "UPS",
                "2026-07-02", "2026-07-05", "2026-07-05", "delivered",
                json.dumps(["ITEM-9032-1"])
            ),
            (
                "SHIP-406", "ORD-9033", "92612999910987654321", "FedEx",
                "2026-05-11", "2026-05-14", "2026-05-14", "delivered",
                json.dumps(["ITEM-9033-1", "ITEM-9033-2"])
            ),
        ]
        cur.executemany(
            """INSERT INTO shipments (
                shipment_id, order_id, tracking_number, carrier,
                ship_date, estimated_delivery, actual_delivery, status, item_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            shipments,
        )

        # ==========================================
        # 5. RETURNS
        # ==========================================
        returns = [
            # RET-701: Open return (refund_processing) for Marcus (ORD-9031)
            (
                "RET-701", "ORD-9031", "ITEM-9031-1", "CUST-103",
                "RMA-AMZ-701-9031", "2026-08-14", "unwanted", "opened_unused",
                "refund_processing", 89.50, None, 0.0
            ),
            # RET-702: Completed refund for Marcus (ORD-9033)
            (
                "RET-702", "ORD-9033", "ITEM-9033-1", "CUST-103",
                "RMA-IKA-702-9033", "2026-05-20", "unwanted", "unopened",
                "completed", 60.48, "2026-05-25", 0.0
            ),
        ]
        cur.executemany(
            """INSERT INTO returns (
                return_id, order_id, line_item_id, customer_id,
                rma_code, request_date, reason, condition, status,
                refund_amount, refund_date, restocking_fee
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            returns,
        )

    print(f"[seed_records] Successfully seeded deterministic database at {db_path}", file=sys.stderr)


def verify_database(db_path: Path = DB_PATH) -> bool:
    """Run strict verification assertions on seeded database."""
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # 1. CUST-101 has exactly 2 orders (1 captured, 1 auth_hold)
        cur.execute("SELECT order_id, status, payment_status, total_amount FROM orders WHERE customer_id = 'CUST-101' ORDER BY order_id;")
        c101_orders = [dict(r) for r in cur.fetchall()]
        assert len(c101_orders) == 2, f"CUST-101 expected 2 orders, got {len(c101_orders)}"
        assert c101_orders[0]["payment_status"] == "captured" and c101_orders[0]["status"] == "delivered"
        assert c101_orders[1]["payment_status"] == "authorized" and c101_orders[1]["status"] == "auth_hold"
        assert c101_orders[0]["total_amount"] == c101_orders[1]["total_amount"] == 129.99

        # 2. CUST-102 has 1 order and 2 shipments (split shipment)
        cur.execute("SELECT order_id, status FROM orders WHERE customer_id = 'CUST-102';")
        c102_orders = [dict(r) for r in cur.fetchall()]
        assert len(c102_orders) == 1 and c102_orders[0]["status"] == "partially_shipped"
        cur.execute("SELECT shipment_id, status, tracking_number FROM shipments WHERE order_id = 'ORD-9021' ORDER BY shipment_id;")
        c102_shipments = [dict(r) for r in cur.fetchall()]
        assert len(c102_shipments) == 2, f"ORD-9021 expected 2 shipments, got {len(c102_shipments)}"
        assert c102_shipments[0]["status"] == "delivered"
        assert c102_shipments[1]["status"] == "in_transit"

        # 3. CUST-103 has 3 orders, 2 returns (1 processing, 1 completed)
        cur.execute("SELECT order_id, order_date, brand FROM orders WHERE customer_id = 'CUST-103' ORDER BY order_date DESC;")
        c103_orders = [dict(r) for r in cur.fetchall()]
        assert len(c103_orders) == 3, f"CUST-103 expected 3 orders, got {len(c103_orders)}"
        cur.execute("SELECT return_id, status, refund_amount FROM returns WHERE customer_id = 'CUST-103' ORDER BY return_id;")
        c103_returns = [dict(r) for r in cur.fetchall()]
        assert len(c103_returns) == 2, f"CUST-103 expected 2 returns, got {len(c103_returns)}"
        assert c103_returns[0]["status"] == "refund_processing" and c103_returns[0]["refund_amount"] == 89.50
        assert c103_returns[1]["status"] == "completed" and c103_returns[1]["refund_amount"] == 60.48

        # 4. Total refunded completed aggregate for CUST-103 is $60.48
        cur.execute("SELECT COALESCE(SUM(refund_amount), 0.0) AS total_refunded FROM returns WHERE customer_id = 'CUST-103' AND status = 'completed';")
        total_refunded = cur.fetchone()["total_refunded"]
        assert abs(total_refunded - 60.48) < 0.001, f"Expected total_refunded=60.48, got {total_refunded}"

        # 5. Non-existent order returns empty result
        cur.execute("SELECT * FROM orders WHERE order_id = 'ORD-99999999';")
        empty_res = cur.fetchall()
        assert len(empty_res) == 0, f"Expected empty result for ORD-99999999, got {len(empty_res)}"

        # 6. Foreign key cascade verification
        cur.execute("SELECT COUNT(*) AS count FROM line_items;")
        assert cur.fetchone()["count"] == 8
        cur.execute("SELECT COUNT(*) AS count FROM shipments;")
        assert cur.fetchone()["count"] == 6
        cur.execute("SELECT COUNT(*) AS count FROM returns;")
        assert cur.fetchone()["count"] == 2

    print("[verify_database] ALL ASSERTIONS PASSED (6/6). Relational foundation verified.", file=sys.stderr)
    return True


if __name__ == "__main__":
    seed_records()
    verify_database()
