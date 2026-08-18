"""Direct unit tests for server/records.py (without MCP protocol)."""

from server.records import RetailRecords, get_retail_schema


def test_query_orders_single_and_line_items():
    records = RetailRecords()
    res = records.query_orders(order_id="ORD-9031")
    assert res["total_found"] == 1
    order = res["results"][0]
    assert order["order_id"] == "ORD-9031"
    assert order["brand"] == "amazon"
    assert order["order_date"] == "2026-08-06"
    assert order["status"] == "delivered"
    assert len(order["line_items"]) == 1
    assert order["line_items"][0]["product_name"] == "Sony WH-CH520 Wireless Headphones"


def test_query_orders_empty_result_q28():
    records = RetailRecords()
    res = records.query_orders(order_id="ORD-99999999")
    assert res["total_found"] == 0
    assert res["results"] == []
    assert res["query"]["order_id"] == "ORD-99999999"


def test_query_orders_duplicate_auth_hold_q14():
    records = RetailRecords()
    res = records.query_orders(customer_id="CUST-101")
    assert res["total_found"] == 2
    orders = sorted(res["results"], key=lambda x: x["order_id"])
    assert orders[0]["order_id"] == "ORD-9011" and orders[0]["payment_status"] == "captured"
    assert orders[1]["order_id"] == "ORD-9012" and orders[1]["payment_status"] == "authorized"
    assert orders[1]["status"] == "auth_hold"


def test_query_shipments_split_order_q8_q9_q13_q16():
    records = RetailRecords()
    res = records.query_shipments(order_id="ORD-9021")
    assert res["total_found"] == 2
    shipments = sorted(res["results"], key=lambda x: x["shipment_id"])
    assert shipments[0]["shipment_id"] == "SHIP-402"
    assert shipments[0]["status"] == "delivered"
    assert shipments[0]["items"][0]["product_name"] == "Ninja Personal Blender"

    assert shipments[1]["shipment_id"] == "SHIP-403"
    assert shipments[1]["status"] == "in_transit"
    assert shipments[1]["actual_delivery"] is None
    assert shipments[1]["items"][0]["product_name"] == "Brita Water Filter Pitcher (6 Cup)"


def test_query_returns_and_status_filtering_q10_q17():
    records = RetailRecords()
    # All returns for CUST-103
    res = records.query_returns(customer_id="CUST-103")
    assert res["total_found"] == 2

    # Filter open returns (refund_processing)
    open_res = records.query_returns(customer_id="CUST-103", status="refund_processing")
    assert open_res["total_found"] == 1
    assert open_res["results"][0]["return_id"] == "RET-701"
    assert open_res["results"][0]["refund_amount"] == 89.50
    assert open_res["results"][0]["refund_date"] is None

    # Filter completed returns
    comp_res = records.query_returns(customer_id="CUST-103", status="completed")
    assert comp_res["total_found"] == 1
    assert comp_res["results"][0]["return_id"] == "RET-702"
    assert comp_res["results"][0]["refund_amount"] == 60.48
    assert comp_res["results"][0]["refund_date"] == "2026-05-25"


def test_query_customer_deterministic_aggregates_q11_q12():
    records = RetailRecords()
    res = records.query_customer(customer_id="CUST-103")
    assert res["total_found"] == 1
    cust = res["results"][0]
    assert cust["name"] == "Marcus Vance"
    aggs = cust["aggregates_2026"]
    # 3 orders placed in 2026
    assert aggs["orders_placed_count"] == 3
    # Exactly $60.48 completed refunds (processing $89.50 is not counted in completed)
    assert aggs["total_refunded_completed"] == 60.48
    assert aggs["open_returns_count"] == 1
    assert aggs["pending_refund_amount"] == 89.50


def test_get_retail_schema_resource():
    schema = get_retail_schema()
    assert schema["resource"] == "kb://retail/schema"
    assert set(schema["tables"].keys()) == {"customers", "orders", "line_items", "shipments", "returns"}
    assert "supported_tools" in schema
