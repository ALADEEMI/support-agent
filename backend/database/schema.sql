-- تعريف جداول قاعدة بيانات نظام دعم العملاء.
-- مطابق حرفياً لـ docs/ADR.md قسم 4.

CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('قيد التجهيز', 'قيد الشحن', 'تم التوصيل', 'ملغي')),
    order_date TEXT NOT NULL,
    expected_delivery TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS policies (
    policy_type TEXT PRIMARY KEY,   -- 'return' / 'refund' / 'shipping'
    description TEXT NOT NULL,
    days_limit INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    customer_message TEXT NOT NULL,
    category TEXT NOT NULL,
    order_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved INTEGER DEFAULT 0
);

-- سجل المحادثة الدائم (منفصل عن ذاكرة LangGraph الداخلية — راجع قسم 1.1)
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK (sender IN ('customer', 'agent')),
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tickets_session ON tickets(session_id);
