"""اتصال SQLite ودوال CRUD لقاعدة بيانات نظام دعم العملاء.

المسار الافتراضي للقاعدة يُقرأ من `config.DATABASE_PATH` (متغير البيئة
`DATABASE_PATH`)، وإذا كان نسبياً فيُحلّ بالنسبة لمجلد `backend/`.

هذه الطبقة تتعامل مع SQLite مباشرة؛ الأدوات في `agent/tools.py` هي التي تُغلّف
الأخطاء وترجع رسائل منظّمة (ADR قسم 7).
"""

import json
import sqlite3
from pathlib import Path

import config

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _migrate_chat_messages_metadata(connection: sqlite3.Connection) -> bool:
    """يضيف عمود `metadata` إلى `chat_messages` في قاعدة بيانات قديمة (ترحيل آمن).

    السبب: `CREATE TABLE IF NOT EXISTS` لا يُعدّل جدولاً قائماً، فقاعدة أُنشئت قبل
    Phase 8 تفتقد العمود. الفحص عبر `PRAGMA table_info` يجعل الترحيل **عديم الأثر**
    عند تكراره (idempotent).

    المدخلات:
        connection (sqlite3.Connection): اتصال مفتوح بقاعدة البيانات.

    المخرجات:
        bool: `True` إذا أُضيف العمود الآن، و`False` إذا كان موجوداً أصلاً.

    حالات الفشل:
        sqlite3.Error: إذا فشل استعلام الـ PRAGMA أو تنفيذ `ALTER TABLE`.
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)")}
    if "metadata" in columns:
        return False
    connection.execute("ALTER TABLE chat_messages ADD COLUMN metadata TEXT")
    return True


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
    """ينشئ جداول قاعدة البيانات من ملف الـ schema، ويُطبّق الترحيلات الإضافية.

    المدخلات:
        db_path (str | None): مسار القاعدة، أو `None` للافتراضي.
        schema_path (str | None): مسار ملف `schema.sql`، أو `None` للمسار الافتراضي.

    المخرجات:
        str: مسار قاعدة البيانات الذي تمت تهيئته.

    حالات الفشل:
        FileNotFoundError: إذا لم يوجد ملف الـ schema.
        sqlite3.Error: إذا فشل تنفيذ الـ schema أو أحد الترحيلات.
    """
    schema_file = Path(schema_path) if schema_path else SCHEMA_PATH
    if not schema_file.exists():
        raise FileNotFoundError(f"ملف الـ schema غير موجود: {schema_file}")

    sql = schema_file.read_text(encoding="utf-8")
    connection = get_connection(db_path)
    try:
        connection.executescript(sql)
        # ترحيلات القواعد القديمة (CREATE TABLE IF NOT EXISTS لا يعدّل جدولاً قائماً).
        _migrate_chat_messages_metadata(connection)
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


def add_chat_message(
    session_id: str,
    sender: str,
    content: str,
    metadata: dict | None = None,
) -> int:
    """يضيف رسالة إلى سجل المحادثة الدائم.

    المدخلات:
        session_id (str): معرّف الجلسة.
        sender (str): `customer` أو `agent`.
        content (str): نص الرسالة.
        metadata (dict | None): حِمولة منظّمة تُخزَّن كسلسلة JSON (مثل
            `{"order_details": {...}}`) ليعاد بناء بطاقة الطلب عند فتح الجلسة لاحقاً.

    المخرجات:
        int: `message_id` للصف المُضاف.

    حالات الفشل:
        sqlite3.Error: إذا فشل الإدراج (بما في ذلك مخالفة قيد `sender`).
    """
    payload = json.dumps(metadata, ensure_ascii=False) if metadata else None
    connection = get_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO chat_messages (session_id, sender, content, metadata) VALUES (?, ?, ?, ?)",
            (session_id, sender, content, payload),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_chat_history(session_id: str) -> list[dict]:
    """يجلب سجل المحادثة لجلسة معيّنة مرتّباً زمنياً، مع فكّ حِمولة `metadata`.

    المدخلات:
        session_id (str): معرّف الجلسة.

    المخرجات:
        list[dict]: قائمة رسائل، كل رسالة بمفاتيح `message_id`, `sender`,
            `content`, `timestamp`, `metadata` (قاموس مفكوك أو `None`)،
            و`order_details` (اختصار لـ `metadata["order_details"]` أو `None`)
            لتسهيل رسم بطاقة الطلب. قائمة فارغة إذا لا يوجد سجل.

    حالات الفشل:
        sqlite3.Error: إذا فشل الاتصال أو الاستعلام. سلاسل JSON تالفة تُتجاهل
            (تُعاد `metadata` كـ `None`) بدل إسقاط السجل.
    """
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT message_id, sender, content, metadata, timestamp
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY message_id ASC
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    history = []
    for row in rows:
        record = dict(row)
        raw_metadata = record.pop("metadata", None)
        parsed = None
        if raw_metadata:
            try:
                parsed = json.loads(raw_metadata)
            except (TypeError, ValueError):
                parsed = None
        record["metadata"] = parsed
        record["order_details"] = (
            parsed.get("order_details") if isinstance(parsed, dict) else None
        )
        history.append(record)
    return history


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


def record_turn_outcome(
    session_id: str,
    category: str,
    low_confidence: bool,
    tool_outcome: str,
    had_error: bool = False,
) -> int:
    """يسجّل مقياساً مختصراً عن دورة محادثة واحدة (لاشتقاق حالة الجلسة).

    المدخلات:
        session_id (str): معرّف الجلسة.
        category (str): الفئة المصنّفة لهذه الدورة.
        low_confidence (bool): هل كانت الثقة تحت العتبة.
        tool_outcome (str): نتيجة الأدوات (`order_found`, `order_not_found`,
            `policy_found`, `policy_missing`, `ticket_created`, `ticket_skipped`, `none`).
        had_error (bool): هل انتهت الدورة بخطأ (فشل LLM أو خطأ داخلي).

    المخرجات:
        int: `outcome_id` للصف المُضاف.

    حالات الفشل:
        sqlite3.Error: إذا فشل الإدراج — بما في ذلك جدول `turn_outcomes` غير موجود
            في قاعدة قديمة (شغّل `python database/seed_data.py` لإنشائه).
    """
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO turn_outcomes (session_id, category, low_confidence, tool_outcome, had_error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, category, 1 if low_confidence else 0, tool_outcome, 1 if had_error else 0),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


# حالات الجلسة المعتمدة في `/api/sessions` (المفاتيح برمجية، والواجهة تترجمها لعربية).
SESSION_STATUS_ESCALATED = "escalated"
SESSION_STATUS_RESOLVED = "resolved"
SESSION_STATUS_UNRESOLVED = "unresolved"
SESSION_STATUS_ACTIVE = "active"

# نتائج أدوات تعني أن الاستعلام نجح (تُحسب «تم الحل»).
_RESOLVING_OUTCOMES = ("order_found", "policy_found", "ticket_created", "ticket_skipped")
# نتائج أدوات تعني أن الاستعلام فشل (تُحسب «معلقة»).
_UNRESOLVING_OUTCOMES = ("order_not_found", "policy_missing")


def _derive_session_status(session: dict, ticket_id: int | None, last_outcome: dict | None) -> str:
    """يشتقّ حالة الجلسة من بياناتها الفعلية (لا تخميناً من النص).

    القواعد بالترتيب:
        1. وجود تذكرة لهذه الجلسة => `escalated` (تذكرة متابعة).
        2. آخر رسالة من العميل بلا رد => `unresolved` (انتهت بلا إجابة، خطأ أو انقطاع).
        3. آخر دورة انتهت بخطأ أو بثقة منخفضة => `unresolved`.
        4. آخر دورة استعلمت ولم تجد النتيجة (طلب/سياسة غير موجودة) => `unresolved`.
        5. آخر دورة نجح استعلامها => `resolved` (تم الحل).
        6. غير ذلك (محادثة عامة بلا استعلام) => `active`.

    المدخلات:
        session (dict): صف مُجمَّع من `chat_messages` (يُقرأ منه `last_sender`).
        ticket_id (int | None): رقم تذكرة مرتبطة بالجلسة إن وُجد.
        last_outcome (dict | None): آخر صف في `turn_outcomes` لهذه الجلسة.

    المخرجات:
        str: أحد ثوابت `SESSION_STATUS_*`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    if ticket_id is not None:
        return SESSION_STATUS_ESCALATED
    if session.get("last_sender") == "customer":
        return SESSION_STATUS_UNRESOLVED
    if not last_outcome:
        # جلسة قديمة بلا مقاييس دورات => الحكم من آخر مرسل فقط.
        return SESSION_STATUS_RESOLVED
    if last_outcome.get("had_error") or last_outcome.get("low_confidence"):
        return SESSION_STATUS_UNRESOLVED
    outcome = last_outcome.get("tool_outcome") or "none"
    if outcome in _UNRESOLVING_OUTCOMES:
        return SESSION_STATUS_UNRESOLVED
    if outcome in _RESOLVING_OUTCOMES:
        return SESSION_STATUS_RESOLVED
    return SESSION_STATUS_ACTIVE


def list_chat_sessions() -> list[dict]:
    """يرجع ملخّص كل جلسة محادثة مع حالتها، مرتّباً بالأحدث أولاً.

    المدخلات:
        لا يوجد.

    المخرجات:
        list[dict]: لكل جلسة: `session_id`, `first_message` (معاينة أول رسالة عميل),
            `last_message` (آخر رسالة), `updated_at`, `message_count`, `ticket_id`,
            `status` (أحد `escalated`/`resolved`/`unresolved`/`active`).

    حالات الفشل:
        sqlite3.Error: إذا فشل الاستعلام. **استثناء واحد:** غياب جدول
            `turn_outcomes` في قاعدة قديمة لا يُسقط الاستدعاء، بل تُشتقّ الحالة
            من الرسائل والتذاكر فقط (مع بقاء `active` غير مستخدم آنذاك).
    """
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT c.session_id,
                   COUNT(*) AS message_count,
                   MIN(c.timestamp) AS started_at,
                   MAX(c.timestamp) AS updated_at,
                   (SELECT m2.content FROM chat_messages AS m2
                     WHERE m2.session_id = c.session_id AND m2.sender = 'customer'
                     ORDER BY m2.message_id ASC LIMIT 1) AS first_message,
                   (SELECT m3.content FROM chat_messages AS m3
                     WHERE m3.session_id = c.session_id
                     ORDER BY m3.message_id DESC LIMIT 1) AS last_message,
                   (SELECT m4.sender FROM chat_messages AS m4
                     WHERE m4.session_id = c.session_id
                     ORDER BY m4.message_id DESC LIMIT 1) AS last_sender
            FROM chat_messages AS c
            GROUP BY c.session_id
            ORDER BY updated_at DESC, c.session_id ASC
            """
        ).fetchall()
        sessions = [dict(row) for row in rows]

        tickets = {
            row["session_id"]: row["ticket_id"]
            for row in connection.execute(
                "SELECT session_id, MAX(ticket_id) AS ticket_id FROM tickets GROUP BY session_id"
            )
        }

        try:
            outcomes = {
                row["session_id"]: dict(row)
                for row in connection.execute(
                    """
                    SELECT session_id, category, low_confidence, tool_outcome, had_error
                    FROM turn_outcomes
                    WHERE outcome_id IN (SELECT MAX(outcome_id) FROM turn_outcomes GROUP BY session_id)
                    """
                )
            }
        except sqlite3.OperationalError:
            outcomes = {}
    finally:
        connection.close()

    return [
        {
            "session_id": session["session_id"],
            "first_message": session["first_message"],
            "last_message": session["last_message"],
            "updated_at": session["updated_at"],
            "message_count": session["message_count"],
            "ticket_id": tickets.get(session["session_id"]),
            "status": _derive_session_status(
                session, tickets.get(session["session_id"]), outcomes.get(session["session_id"])
            ),
        }
        for session in sessions
    ]


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
