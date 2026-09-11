"""اتصال SQLite ودوال CRUD لقاعدة بيانات نظام دعم العملاء.

المسار الافتراضي للقاعدة يُقرأ من `config.DATABASE_PATH` (متغير البيئة
`DATABASE_PATH`)، وإذا كان نسبياً فيُحلّ بالنسبة لمجلد `backend/`.

هذه الطبقة تتعامل مع SQLite مباشرة؛ الأدوات في `agent/tools.py` هي التي تُغلّف
الأخطاء وترجع رسائل منظّمة (ADR قسم 7).
"""

import sqlite3
from pathlib import Path

import config

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def resolve_db_path(db_path: str | None = None) -> str:
    """يحلّ مسار قاعدة البيانات إلى مسار مطلق.

    المدخلات:
        db_path (str | None): مسار صريح للقاعدة، أو `None` لاستخدام `config.DATABASE_PATH`.

    المخرجات:
        str: مسار مطلق لملف قاعدة البيانات.

    حالات الفشل:
        لا يرفع استثناءات — يعيد المسار المحلول دون التحقق من وجود الملف.
    """
    raw = db_path if db_path is not None else config.DATABASE_PATH
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return str(path)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """يفتح اتصالاً بقاعدة SQLite مع تفعيل المفاتيح الأجنبية.

    المدخلات:
        db_path (str | None): مسار القاعدة، أو `None` للافتراضي.

    المخرجات:
        sqlite3.Connection: اتصال جاهز، صفوفه من نوع `sqlite3.Row`.

    حالات الفشل:
        sqlite3.Error: إذا تعذّر إنشاء مجلد القاعدة أو فتح الاتصال.
    """
    resolved = resolve_db_path(db_path)
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: str | None = None, schema_path: str | None = None) -> str:
    """ينشئ جداول قاعدة البيانات من ملف الـ schema.

    المدخلات:
        db_path (str | None): مسار القاعدة، أو `None` للافتراضي.
        schema_path (str | None): مسار ملف `schema.sql`، أو `None` للمسار الافتراضي.

    المخرجات:
        str: مسار قاعدة البيانات الذي تمت تهيئته.

    حالات الفشل:
        FileNotFoundError: إذا لم يوجد ملف الـ schema.
        sqlite3.Error: إذا فشل تنفيذ الـ schema.
    """
    schema_file = Path(schema_path) if schema_path else SCHEMA_PATH
    if not schema_file.exists():
        raise FileNotFoundError(f"ملف الـ schema غير موجود: {schema_file}")

    sql = schema_file.read_text(encoding="utf-8")
    connection = get_connection(db_path)
    try:
        connection.executescript(sql)
        connection.commit()
    finally:
        connection.close()
    return resolve_db_path(db_path)


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """يحوّل صفاً واحداً إلى قاموس، أو `None` إذا كان الصف فارغاً.

    المدخلات:
        row (sqlite3.Row | None): الصف القادم من الاستعلام.

    المخرجات:
        dict | None: الصف كقاموس، أو `None`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return dict(row) if row is not None else None


def get_order_with_product(order_id: int) -> dict | None:
    """يجلب طلباً مع اسم المنتج المرتبط به.

    المدخلات:
        order_id (int): رقم الطلب.

    المخرجات:
        dict | None: مفاتيحها `order_id`, `customer_id`, `product_name`, `status`,
            `order_date`, `expected_delivery` — أو `None` إذا لم يوجد الطلب.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام.
    """
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT o.order_id, o.customer_id, p.product_name, o.status,
                   o.order_date, o.expected_delivery
            FROM orders AS o
            JOIN products AS p ON p.product_id = o.product_id
            WHERE o.order_id = ?
            """,
            (order_id,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def get_policy(policy_type: str) -> dict | None:
    """يجلب سياسة واحدة بنوعها.

    المدخلات:
        policy_type (str): نوع السياسة (`return` / `refund` / `shipping`).

    المخرجات:
        dict | None: مفاتيحها `policy_type`, `description`, `days_limit` —
            أو `None` إذا لم توجد السياسة.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام.
    """
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT policy_type, description, days_limit FROM policies WHERE policy_type = ?",
            (policy_type,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def create_ticket(session_id: str, message: str, category: str, order_id: int | None = None) -> int:
    """يُنشئ صفاً جديداً في جدول التذاكر.

    المدخلات:
        session_id (str): معرّف الجلسة.
        message (str): رسالة العميل الأصلية.
        category (str): الفئة المصنّفة.
        order_id (int | None): رقم الطلب إن وُجد.

    المخرجات:
        int: `ticket_id` للصف المُنشأ.

    حالات الفشل:
        sqlite3.Error: إذا فشل الإدراج.
    """
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO tickets (session_id, customer_message, category, order_id)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, message, category, order_id),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def add_chat_message(session_id: str, sender: str, content: str) -> int:
    """يضيف رسالة إلى سجل المحادثة الدائم.

    المدخلات:
        session_id (str): معرّف الجلسة.
        sender (str): `customer` أو `agent`.
        content (str): نص الرسالة.

    المخرجات:
        int: `message_id` للصف المُضاف.

    حالات الفشل:
        sqlite3.Error: إذا فشل الإدراج (بما في ذلك مخالفة قيد `sender`).
    """
    connection = get_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO chat_messages (session_id, sender, content) VALUES (?, ?, ?)",
            (session_id, sender, content),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_chat_history(session_id: str) -> list[dict]:
    """يجلب سجل المحادثة لجلسة معيّنة مرتّباً زمنياً.

    المدخلات:
        session_id (str): معرّف الجلسة.

    المخرجات:
        list[dict]: قائمة رسائل، كل رسالة بمفاتيح `message_id`, `sender`,
            `content`, `timestamp`. قائمة فارغة إذا لا يوجد سجل.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام.
    """
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT message_id, sender, content, timestamp
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY message_id ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_product_by_name(product_name: str) -> dict | None:
    """يجلب منتجاً باسمه.

    المدخلات:
        product_name (str): اسم المنتج.

    المخرجات:
        dict | None: مفاتيحها `product_id`, `product_name` — أو `None`.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام.
    """
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT product_id, product_name FROM products WHERE product_name = ?",
            (product_name,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        connection.close()


def list_products() -> list[dict]:
    """يجلب كل المنتجات.

    المدخلات:
        لا يوجد.

    المخرجات:
        list[dict]: قائمة منتجات بمفاتيح `product_id`, `product_name`.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام.
    """
    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT product_id, product_name FROM products ORDER BY product_id ASC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def count_rows(table: str) -> int:
    """يرجع عدد صفوف جدول معيّن (يُستخدم في التحقق والتشخيص).

    المدخلات:
        table (str): اسم الجدول.

    المخرجات:
        int: عدد الصفوف.

    حالات الفشل:
        sqlite3.Error: إذا كان اسم الجدول غير صالح أو فشل الاستعلام.
    """
    connection = get_connection()
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()
