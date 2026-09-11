"""اختبارات الأدوات الثلاث (ADR قسم 7 و 10).

تُستخدم قاعدة بيانات تجريبية منفصلة تماماً عن قاعدة البيانات الفعلية، تُبنى في
مجلد مؤقت ويُوجَّه `config.DATABASE_PATH` إليها عبر monkeypatch.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from agent import tools  # noqa: E402
from database import db  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """ينشئ قاعدة بيانات تجريبية معزولة ويعبّئها ببيانات اختبار.

    المخرجات:
        Path: مسار ملف قاعدة البيانات المؤقت.

    حالات الفشل:
        sqlite3.Error: إذا فشل إنشاء القاعدة أو إدخال البيانات.
    """
    db_path = tmp_path / "test_support.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_path))

    db.init_db(str(db_path))
    connection = db.get_connection(str(db_path))
    try:
        connection.execute("INSERT INTO customers (customer_id, name, phone) VALUES (1, 'عميل اختبار', '000')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (1, 'لابتوب ديل')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (2, 'شاحن سريع')")
        connection.execute(
            """INSERT INTO orders (order_id, customer_id, product_id, status, order_date, expected_delivery)
               VALUES (5001, 1, 1, 'قيد الشحن', '2026-09-01', '2026-09-10')"""
        )
        connection.execute(
            """INSERT INTO policies (policy_type, description, days_limit)
               VALUES ('return', 'يمكن الإرجاع خلال 14 يوماً.', 14)"""
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


def test_check_order_status_found(temp_db):
    """أداة حالة الطلب ترجع البيانات الكاملة عند وجود الطلب."""
    result = tools.check_order_status(5001)
    assert result["found"] is True
    assert result["order_id"] == 5001
    assert result["status"] == "قيد الشحن"
    assert result["product_name"] == "لابتوب ديل"
    assert result["expected_delivery"] == "2026-09-10"


def test_check_order_status_not_found(temp_db):
    """أداة حالة الطلب لا تفترض النجاح: ترجع `found=False` لطلب غير موجود."""
    result = tools.check_order_status(999999)
    assert result["found"] is False
    assert result["order_id"] == 999999
    assert "status" not in result


def test_check_order_status_database_error(monkeypatch, tmp_path):
    """فشل قاعدة البيانات يُعاد كرسالة منظّمة داخل `error` بلا exception خام."""
    bad_path = tmp_path / "a_directory"
    bad_path.mkdir()
    monkeypatch.setattr(config, "DATABASE_PATH", str(bad_path))

    result = tools.check_order_status(5001)
    assert result["found"] is False
    assert "error" in result
    assert "تعذّر الوصول" in result["error"]


def test_check_policy_found(temp_db):
    """أداة السياسة ترجع النص والحد الزمني عند وجود السياسة."""
    result = tools.check_policy("return")
    assert result["found"] is True
    assert result["policy_type"] == "return"
    assert result["days_limit"] == 14
    assert "الإرجاع" in result["description"]


def test_check_policy_not_found(temp_db):
    """سياسة غير موجودة => `found=False` بلا نص."""
    result = tools.check_policy("shipping")
    assert result["found"] is False
    assert result["policy_type"] == "shipping"
    assert "description" not in result


def test_check_policy_database_error(monkeypatch, tmp_path):
    """فشل قاعدة البيانات في أداة السياسة يعود كرسالة منظّمة."""
    bad_path = tmp_path / "a_directory2"
    bad_path.mkdir()
    monkeypatch.setattr(config, "DATABASE_PATH", str(bad_path))

    result = tools.check_policy("return")
    assert result["found"] is False
    assert "error" in result


def test_create_ticket_returns_id(temp_db):
    """أداة التذكرة تُنشئ صفاً وترجع معرّفه."""
    result = tools.create_ticket("sess-1", "الطلب متأخر", "complaint", 5001)
    assert result["created"] is True
    assert isinstance(result["ticket_id"], int)

    connection = db.get_connection(str(temp_db))
    try:
        row = connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (result["ticket_id"],)).fetchone()
        assert row["session_id"] == "sess-1"
        assert row["category"] == "complaint"
        assert row["order_id"] == 5001
        assert row["resolved"] == 0
    finally:
        connection.close()


def test_create_ticket_without_order_id(temp_db):
    """التذكرة تُنشأ برقم طلب `None` عندما لا يُذكر طلب."""
    result = tools.create_ticket("sess-2", "شكوى عامة", "complaint", None)
    assert result["created"] is True

    connection = db.get_connection(str(temp_db))
    try:
        row = connection.execute("SELECT order_id FROM tickets WHERE ticket_id = ?", (result["ticket_id"],)).fetchone()
        assert row["order_id"] is None
    finally:
        connection.close()


def test_create_ticket_database_error(monkeypatch, tmp_path):
    """فشل قاعدة البيانات في أداة التذكرة يعود كرسالة منظّمة."""
    bad_path = tmp_path / "a_directory3"
    bad_path.mkdir()
    monkeypatch.setattr(config, "DATABASE_PATH", str(bad_path))

    result = tools.create_ticket("sess-3", "شكوى", "complaint", None)
    assert result["created"] is False
    assert "error" in result


def test_tools_never_write_to_real_database(temp_db):
    """تأكيد أن الاختبارات لا تلمس قاعدة البيانات الفعلية."""
    real_path = db.resolve_db_path(config.DATABASE_PATH)
    assert "test_support.db" in real_path
