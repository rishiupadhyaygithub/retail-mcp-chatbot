-- Retail Knowledge & Operational Records Database Schema (Phase 2)
-- Relational model for Retail/E-Commerce operational entities:
-- customers -> orders -> line_items, shipments, returns

PRAGMA foreign_keys = ON;

-- 1. Customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'closed'))
);

-- 2. Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    brand TEXT NOT NULL CHECK (brand IN ('amazon', 'bestbuy', 'ikea', 'target')),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'shipped', 'partially_shipped', 'delivered', 'cancelled', 'auth_hold')),
    payment_status TEXT NOT NULL CHECK (payment_status IN ('authorized', 'captured', 'refunded', 'partially_refunded', 'voided')),
    subtotal REAL NOT NULL,
    tax REAL NOT NULL,
    shipping_cost REAL NOT NULL,
    total_amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    shipping_address TEXT NOT NULL,
    notes TEXT
);

-- 3. Line Items
CREATE TABLE IF NOT EXISTS line_items (
    line_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_price REAL NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    total_price REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'shipped', 'delivered', 'returned', 'cancelled'))
);

-- 4. Shipments
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    tracking_number TEXT NOT NULL UNIQUE,
    carrier TEXT NOT NULL,
    ship_date TEXT NOT NULL,
    estimated_delivery TEXT NOT NULL,
    actual_delivery TEXT,
    status TEXT NOT NULL CHECK (status IN ('label_created', 'in_transit', 'out_for_delivery', 'delivered', 'failed_attempt', 'returned_to_sender')),
    item_ids_json TEXT NOT NULL
);

-- 5. Returns
CREATE TABLE IF NOT EXISTS returns (
    return_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    line_item_id TEXT NOT NULL REFERENCES line_items(line_item_id) ON DELETE CASCADE,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    rma_code TEXT NOT NULL UNIQUE,
    request_date TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('damaged', 'defective', 'wrong_item', 'unwanted', 'not_as_described', 'late_delivery')),
    condition TEXT NOT NULL CHECK (condition IN ('unopened', 'opened_unused', 'used', 'damaged')),
    status TEXT NOT NULL CHECK (status IN ('requested', 'approved', 'label_generated', 'in_transit', 'received', 'inspecting', 'refund_processing', 'completed', 'rejected')),
    refund_amount REAL NOT NULL,
    refund_date TEXT,
    restocking_fee REAL NOT NULL DEFAULT 0.0
);

-- Indices for fast semantic lookups
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_line_items_order ON line_items(order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tracking_number);
CREATE INDEX IF NOT EXISTS idx_returns_order ON returns(order_id);
CREATE INDEX IF NOT EXISTS idx_returns_customer ON returns(customer_id);
CREATE INDEX IF NOT EXISTS idx_returns_status ON returns(status);
