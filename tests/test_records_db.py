"""Unit tests for Phase 2A SQLite Relational Store."""

from pathlib import Path
import sqlite3
from data.seed_records import DB_PATH, seed_records, verify_database, get_connection, REFERENCE_DATE


def test_seed_records_and_verify():
    """Verify that seed_records builds a clean, verified database."""
    seed_records()
    assert verify_database() is True


def test_foreign_key_integrity():
    """Verify that foreign keys are enabled and enforce cascading deletes / references."""
    seed_records()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        assert cur.fetchone()[0] == 1

        # Attempting to insert an order with non-existent customer must fail
        try:
            cur.execute("""
                INSERT INTO orders (
                    order_id, customer_id, brand, order_date, status, payment_status,
                    subtotal, tax, shipping_cost, total_amount, currency, shipping_address
                ) VALUES ('ORD-FAIL', 'CUST-NONEXISTENT', 'amazon', '2026-08-18', 'delivered', 'captured', 10, 1, 0, 11, 'USD', 'addr');
            """)
            assert False, "Should have raised IntegrityError for missing foreign key customer"
        except sqlite3.IntegrityError:
            pass


def test_evaluation_scenarios_deterministic():
    """Verify the 4 exact operational scenarios matching Q8-17."""
    seed_records()
    with get_connection() as conn:
        cur = conn.cursor()

        # Scenario 1 (Q14): Duplicate auth hold vs settled charge
        cur.execute("SELECT order_id, status, payment_status FROM orders WHERE customer_id = 'CUST-101' ORDER BY order_id;")
        orders_101 = [dict(r) for r in cur.fetchall()]
        assert len(orders_101) == 2
        assert orders_101[0]["order_id"] == "ORD-9011" and orders_101[0]["payment_status"] == "captured"
        assert orders_101[1]["order_id"] == "ORD-9012" and orders_101[1]["payment_status"] == "authorized"

        # Scenario 2 (Q8, Q9, Q13, Q16): Split shipment for ORD-9021
        cur.execute("SELECT shipment_id, carrier, tracking_number, status FROM shipments WHERE order_id = 'ORD-9021' ORDER BY shipment_id;")
        shipments_9021 = [dict(r) for r in cur.fetchall()]
        assert len(shipments_9021) == 2
        assert shipments_9021[0]["status"] == "delivered"
        assert shipments_9021[1]["status"] == "in_transit"

        # Scenario 3 (Q15): Return eligibility based on reference date
        # ORD-9031 placed on 2026-08-06 (12 days before 2026-08-18)
        cur.execute("SELECT order_date, brand FROM orders WHERE order_id = 'ORD-9031';")
        o31 = dict(cur.fetchone())
        assert o31["order_date"] == "2026-08-06"
        assert o31["brand"] == "amazon"

        # ORD-9032 placed on 2026-07-01 (48 days before 2026-08-18)
        cur.execute("SELECT order_date, brand FROM orders WHERE order_id = 'ORD-9032';")
        o32 = dict(cur.fetchone())
        assert o32["order_date"] == "2026-07-01"
        assert o32["brand"] == "bestbuy"

        # Scenario 4 (Q10, Q12, Q17): Return and refund aggregates for CUST-103
        cur.execute("SELECT return_id, status, refund_amount FROM returns WHERE customer_id = 'CUST-103' ORDER BY return_id;")
        rets_103 = [dict(r) for r in cur.fetchall()]
        assert len(rets_103) == 2
        assert rets_103[0]["status"] == "refund_processing"
        assert rets_103[1]["status"] == "completed"
