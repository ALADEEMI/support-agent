"""تعبئة بيانات وهمية أولية (منتجات، عملاء، طلبات، سياسات).

البيانات حتمية (deterministic) وقابلة لإعادة التعبئة في أي وقت، وتستخدم
قائمة المنتجات الـ 15 المعتمدة (المطابقة لأعمدة `product_name` في الداتا سيت).

لإعادة التعبئة:
    python database/seed_data.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import db  # noqa: E402

PRODUCTS = [
    "سماعة بلوتوث",
    "شاحن سريع",
    "ساعة ذكية",
    "جوال سامسونج",
    "لابتوب ديل",
    "طقم مطبخ",
    "مكواة بخار",
    "مكنسة كهربائية",
    "كرسي مكتب",
    "طاولة قهوة",
    "حذاء رياضي",
    "شنطة ظهر",
    "نظارة شمسية",
    "عطر رجالي",
    "بطانية شتوية",
]

CUSTOMERS = [
    ("أحمد الزبيدي", "+967711000101"),
    ("فاطمة الحداد", "+967711000102"),
    ("محمد العمري", "+967711000103"),
    ("سارة الشامي", "+967711000104"),
    ("خالد اليافعي", "+967711000105"),
    ("نورا السقاف", "+967711000106"),
]

POLICIES = [
    (
        "return",
        "يمكن للعميل إرجاع المنتج خلال 14 يوماً من تاريخ الاستلام بشرط أن يكون المنتج "
        "بحالته الأصلية مع الكرتون والملحقات. يتحمل العميل تكلفة الشحن في حالات تغيير "
        "الرأي، وتتحمل الشركة التكلفة إذا كان المنتج معيباً أو مخالفاً للوصف.",
        14,
    ),
    (
        "refund",
        "يُعاد المبلغ بنفس طريقة الدفع خلال 7 أيام عمل من استلام المنتج المرتجع واعتماده "
        "من فريق الجودة. المبالغ النقدية (الدفع عند الاستلام) تُعاد حوالة أو نقداً في الفرع.",
        7,
    ),
    (
        "shipping",
        "التوصيل متاح لجميع المناطق خلال 3 إلى 7 أيام عمل من تاريخ تأكيد الطلب، وقد تتأخر "
        "الطلبات في المواسم. الدفع عند الاستلام متاح، والشحن مجاني للطلبات فوق حد معيّن.",
        None,
    ),
]

# (order_id, customer_id, product_id, status, order_date, expected_delivery)
ORDERS = [
    (1001, 1, 1, "قيد التجهيز", "2026-09-01", "2026-09-12"),
    (1002, 1, 2, "قيد الشحن", "2026-08-28", "2026-09-08"),
    (1003, 2, 3, "تم التوصيل", "2026-08-15", "2026-08-22"),
    (1004, 2, 4, "ملغي", "2026-08-10", None),
    (1005, 3, 5, "قيد الشحن", "2026-09-03", "2026-09-14"),
    (1006, 3, 6, "تم التوصيل", "2026-07-20", "2026-07-27"),
    (1007, 4, 7, "قيد التجهيز", "2026-09-05", "2026-09-15"),
    (1008, 4, 8, "تم التوصيل", "2026-08-01", "2026-08-09"),
    (1009, 5, 9, "قيد الشحن", "2026-09-02", "2026-09-11"),
    (1010, 5, 10, "تم التوصيل", "2026-07-11", "2026-07-18"),
    (1011, 6, 11, "ملغي", "2026-08-05", None),
    (1012, 6, 12, "قيد التجهيز", "2026-09-06", "2026-09-16"),
    (1013, 1, 13, "تم التوصيل", "2026-06-25", "2026-07-02"),
    (1014, 2, 14, "قيد الشحن", "2026-09-04", "2026-09-13"),
    (1015, 3, 15, "تم التوصيل", "2026-08-20", "2026-08-28"),
]

TABLES_IN_CLEAR_ORDER = [
    "turn_outcomes",
    "tickets",
    "chat_messages",
    "orders",
    "policies",
    "products",
    "customers",
]


def clear_seed_tables(connection) -> None:
    """يحذف كل البيانات من جداول البذور بترتيب يحترم المفاتيح الأجنبية.

    المدخلات:
        connection (sqlite3.Connection): اتصال مفتوح بقاعدة البيانات.

    المخرجات:
        None.

    حالات الفشل:
        sqlite3.Error: إذا فشل الحذف.
    """
    for table in TABLES_IN_CLEAR_ORDER:
        connection.execute(f"DELETE FROM {table}")
    connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'customers')")


def seed_all(db_path: str | None = None) -> dict:
    """ينشئ الجداول ثم يعبّئها بالبيانات الوهمية الحتمية (مع مسح أي بيانات سابقة).

    المدخلات:
        db_path (str | None): مسار القاعدة، أو `None` للافتراضي من `config`.

    المخرجات:
        dict: عدد الصفوف المُدخلة لكل جدول، بمفاتيح `customers`, `products`,
            `orders`, `policies`.

    حالات الفشل:
        FileNotFoundError: إذا لم يوجد ملف الـ schema.
        sqlite3.Error: إذا فشل أي إدراج (يُعاد التراجع عن العملية كاملة).
    """
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    try:
        clear_seed_tables(connection)

        connection.executemany(
            "INSERT INTO customers (customer_id, name, phone) VALUES (?, ?, ?)",
            [(index, name, phone) for index, (name, phone) in enumerate(CUSTOMERS, start=1)],
        )
        connection.executemany(
            "INSERT INTO products (product_id, product_name) VALUES (?, ?)",
            [(index, name) for index, name in enumerate(PRODUCTS, start=1)],
        )
        connection.executemany(
            """
            INSERT INTO orders (order_id, customer_id, product_id, status, order_date, expected_delivery)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ORDERS,
        )
        connection.executemany(
            "INSERT INTO policies (policy_type, description, days_limit) VALUES (?, ?, ?)",
            POLICIES,
        )

        connection.commit()
        return {
            "customers": len(CUSTOMERS),
            "products": len(PRODUCTS),
            "orders": len(ORDERS),
            "policies": len(POLICIES),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    """يشغّل التهيئة والتعبئة ويطبع ملخصاً بالنتيجة.

    المدخلات:
        لا يوجد.

    المخرجات:
        None (يطبع المسار وأعداد الصفوف على الطرفية).

    حالات الفشل:
        يرفع الاستثناء لأعلى إذا فشلت التهيئة أو التعبئة.
    """
    counts = seed_all()
    print(f"تم تجهيز قاعدة البيانات: {db.resolve_db_path()}")
    for table, count in counts.items():
        print(f"  - {table}: {count}")


if __name__ == "__main__":
    main()
