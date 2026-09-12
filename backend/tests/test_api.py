"""اختبارات endpoint الواجهة الخلفية `/api/chat` (ADR قسم 10 — Phase 5).

يُستبدَل استدعاء الـ LLM (اعتماد شبكي خارجي) في اختبارات الوحدة عبر monkeypatch،
مع التحقق من أن الردود تُحفظ فعلاً في `chat_messages` وأن الذاكرة تُفصل حسب الجلسة.
تُستخدم قاعدة بيانات تجريبية معزولة، لا قاعدة البيانات الفعلية.
"""

import sys
from pathlib import Path

import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from agent import graph  # noqa: E402
from app import app as flask_app  # noqa: E402
from database import db  # noqa: E402

FIXED_REPLY = "حياك الله يا غالي، تم التحقق من طلبك."


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """قاعدة بيانات اختبار معزولة تحتوي الحد الأدنى اللازم لتشغيل الـ Graph."""
    db_path = tmp_path / "api_test.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_path))

    db.init_db(str(db_path))
    connection = db.get_connection(str(db_path))
    try:
        connection.execute("INSERT INTO customers (customer_id, name, phone) VALUES (1, 'عميل اختبار', '000')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (1, 'شاحن سريع')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (2, 'نظارة شمسية')")
        connection.execute(
            """INSERT INTO orders (order_id, customer_id, product_id, status, order_date, expected_delivery)
               VALUES (1002, 1, 1, 'قيد الشحن', '2026-08-28', '2026-09-08')"""
        )
        connection.execute(
            "INSERT INTO policies (policy_type, description, days_limit) VALUES ('return', 'الإرجاع خلال 14 يوماً.', 14)"
        )
        connection.execute(
            "INSERT INTO policies (policy_type, description, days_limit) VALUES ('refund', 'الاسترجاع خلال 7 أيام.', 7)"
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


@pytest.fixture()
def client(temp_db, monkeypatch, tmp_path):
    """عميل اختبار Flask مع ذاكرة Graph مؤقتة و LLM مُثبَّت."""
    monkeypatch.setattr(graph, "_graph", None)
    monkeypatch.setattr(graph, "_checkpointer", None)
    monkeypatch.setattr(graph, "AGENT_MEMORY_PATH", tmp_path / "api_memory.db")
    monkeypatch.setattr(graph, "call_llm", lambda messages: FIXED_REPLY)
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


def test_health(client):
    """مسار الفحص يعمل."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_chat_happy_path_returns_reply(client):
    """رسالة صحيحة تُرجع رداً وحقلاً منظّماً برمز 200."""
    response = client.post("/api/chat", json={"session_id": "s-1", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"})
    assert response.status_code == 200

    body = response.get_json()
    assert body["session_id"] == "s-1"
    assert body["reply"] == FIXED_REPLY
    assert body["category"] == "order_inquiry"
    assert body["order_id"] == 1002
    assert body["product_name"] == "شاحن سريع"
    assert body["needs_escalation"] is False
    # الحقول المشتقة الجديدة من إصلاح المعمار (Task 1)
    assert body["low_confidence"] is False
    assert body["intent_confidence"] >= 0.65
    assert body["policy_question"] is False
    assert body["ticket_reference"] is None
    assert body["ticket_id"] is None


def test_chat_persists_both_messages(client, temp_db):
    """كل رسالة (العميل ثم الوكيل) تُحفظ في `chat_messages` بالترتيب."""
    client.post("/api/chat", json={"session_id": "s-2", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"})

    connection = db.get_connection(str(temp_db))
    try:
        rows = [dict(r) for r in connection.execute(
            "SELECT sender, content FROM chat_messages WHERE session_id = 's-2' ORDER BY message_id"
        )]
    finally:
        connection.close()

    assert len(rows) == 2
    assert rows[0]["sender"] == "customer"
    assert rows[0]["content"] == "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"
    assert rows[1]["sender"] == "agent"
    assert rows[1]["content"] == FIXED_REPLY


def test_chat_accumulates_history_across_turns(client, temp_db):
    """محادثة من 3 رسائل بنفس `session_id` تُنتج 6 صفوف مرتّبة."""
    messages = [
        "وين وصل طلبي رقم 1002 وهو شاحن سريع؟",
        "طيب متى يوصل بالضبط؟",
        "شكرا لك",
    ]
    for message in messages:
        response = client.post("/api/chat", json={"session_id": "s-3", "message": message})
        assert response.status_code == 200

    connection = db.get_connection(str(temp_db))
    try:
        rows = [dict(r) for r in connection.execute(
            "SELECT sender, content FROM chat_messages WHERE session_id = 's-3' ORDER BY message_id"
        )]
    finally:
        connection.close()

    assert len(rows) == 6
    assert [row["sender"] for row in rows] == ["customer", "agent"] * 3
    assert rows[0]["content"] == messages[0]
    assert rows[4]["content"] == messages[2]


def test_chat_separates_sessions(client, temp_db):
    """كل `session_id` له سجل مستقل."""
    client.post("/api/chat", json={"session_id": "alice", "message": "هلا"})
    client.post("/api/chat", json={"session_id": "bob", "message": "مرحبا"})

    assert len(db.get_chat_history("alice")) == 2
    assert len(db.get_chat_history("bob")) == 2
    assert db.get_chat_history("alice")[0]["content"] == "هلا"


def test_chat_complaint_creates_ticket(client, temp_db):
    """مسار الشكوى ينشئ تذكرة عبر الـ API."""
    response = client.post("/api/chat", json={"session_id": "s-4", "message": "الخدمة سيئة جدا وما احد رد علي حسبي الله"})
    assert response.status_code == 200
    assert response.get_json()["needs_escalation"] is True
    assert db.count_rows("tickets") == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"session_id": "s"},
        {"message": "هلا"},
        {"session_id": "", "message": "هلا"},
        {"session_id": "s", "message": ""},
        {"session_id": "   ", "message": "هلا"},
        {"session_id": 123, "message": "هلا"},
        {"session_id": "s", "message": 456},
    ],
)
def test_chat_validation_returns_400(client, payload):
    """أي حقل ناقص أو غير صالح يعطي 400."""
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_chat_non_json_body_returns_400(client):
    """جسم ليس JSON يعطي 400."""
    response = client.post("/api/chat", data="not json", content_type="text/plain")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_chat_missing_api_key_returns_clear_500(client, monkeypatch):
    """غياب المفتاح يعطي 500 برسالة واضحة بلا أي fallback صامت."""
    monkeypatch.setattr(config, "COMMANDCODE_API_KEY", None)

    def call_llm_without_key(messages):
        config.require_api_key()

    monkeypatch.setattr(graph, "call_llm", call_llm_without_key)

    response = client.post("/api/chat", json={"session_id": "s-5", "message": "هلا"})
    assert response.status_code == 500
    body = response.get_json()
    assert "error" in body
    assert "COMMANDCODE_API_KEY" in body["error"]


def test_chat_upstream_failure_returns_502(client, monkeypatch):
    """فشل مزوّد الـ LLM يعطي 502 برسالة منظّمة."""

    def failing_call_llm(messages):
        raise requests.ConnectionError("upstream down")

    monkeypatch.setattr(graph, "call_llm", failing_call_llm)

    response = client.post("/api/chat", json={"session_id": "s-6", "message": "هلا"})
    assert response.status_code == 502
    assert "error" in response.get_json()


def test_failed_turn_still_persists_customer_message(client, monkeypatch, temp_db):
    """لو فشل الـ LLM، تبقى رسالة العميل محفوظة (لا يُفقد إدخال المستخدم)."""

    def failing_call_llm(messages):
        raise requests.ConnectionError("upstream down")

    monkeypatch.setattr(graph, "call_llm", failing_call_llm)

    client.post("/api/chat", json={"session_id": "s-7", "message": "هلا"})

    history = db.get_chat_history("s-7")
    assert len(history) == 1
    assert history[0]["sender"] == "customer"


def test_history_empty_for_unknown_session(client):
    """جلسة بلا سجل تُرجع قائمة فارغة برمز 200 (لا خطأ)."""
    response = client.get("/api/history/never-seen-session")
    assert response.status_code == 200
    body = response.get_json()
    assert body["session_id"] == "never-seen-session"
    assert body["messages"] == []


def test_history_returns_ordered_messages_after_chat(client):
    """بعد محادثة، السجل يُرجع الرسائل مرتّبة بنفس ترتيب حدوثها."""
    client.post("/api/chat", json={"session_id": "s-8", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"})
    client.post("/api/chat", json={"session_id": "s-8", "message": "طيب متى يوصل بالضبط؟"})

    response = client.get("/api/history/s-8")
    assert response.status_code == 200

    messages = response.get_json()["messages"]
    assert len(messages) == 4
    assert [m["sender"] for m in messages] == ["customer", "agent", "customer", "agent"]
    assert messages[0]["content"] == "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"
    assert messages[1]["content"] == FIXED_REPLY
    assert messages[2]["content"] == "طيب متى يوصل بالضبط؟"
    for message in messages:
        assert set(message.keys()) == {
            "message_id",
            "sender",
            "content",
            "metadata",
            "order_details",
            "timestamp",
        }


def test_history_is_isolated_per_session(client):
    """سجل كل جلسة مستقل عن غيرها."""
    client.post("/api/chat", json={"session_id": "s-9", "message": "هلا"})
    client.post("/api/chat", json={"session_id": "s-10", "message": "مرحبا"})

    first = client.get("/api/history/s-9").get_json()["messages"]
    second = client.get("/api/history/s-10").get_json()["messages"]
    assert [m["content"] for m in first][0] == "هلا"
    assert [m["content"] for m in second][0] == "مرحبا"
    assert len(first) == len(second) == 2


# ---------------------------------------------------------------------------
# Phase 8 — /api/sessions وحالة الجلسة وبطاقة الطلب
# ---------------------------------------------------------------------------


def test_sessions_endpoint_empty(client):
    """لا جلسات => قائمة فارغة برمز 200 (لا خطأ)."""
    response = client.get("/api/sessions")
    assert response.status_code == 200
    assert response.get_json() == {"sessions": []}


def test_sessions_summary_shape_and_ordering(client):
    """ملخّص الجلسات يعرض الحقول المطلوبة ومرتّباً بالأحدث أولاً."""
    client.post("/api/chat", json={"session_id": "old-session", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"})
    client.post("/api/chat", json={"session_id": "new-session", "message": "طيب متى يوصل بالضبط؟"})

    sessions = client.get("/api/sessions").get_json()["sessions"]
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "new-session", "الترتيب ليس بالأحدث أولاً"

    summary = next(s for s in sessions if s["session_id"] == "old-session")
    assert summary["first_message"] == "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"
    assert summary["last_message"] == FIXED_REPLY
    assert summary["message_count"] == 2
    assert summary["updated_at"]
    assert summary["ticket_id"] is None
    assert set(summary.keys()) == {
        "session_id",
        "first_message",
        "last_message",
        "updated_at",
        "message_count",
        "ticket_id",
        "status",
    }


def test_sessions_status_resolved_when_order_found(client):
    """حالة الجلسة = resolved عندما ينجح استعلام الطلب."""
    client.post("/api/chat", json={"session_id": "st-resolved", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"})
    sessions = client.get("/api/sessions").get_json()["sessions"]
    assert sessions[0]["status"] == "resolved"


def test_sessions_status_escalated_when_ticket_exists(client, temp_db):
    """حالة الجلسة = escalated عند وجود تذكرة مرتبطة بها."""
    client.post(
        "/api/chat",
        json={"session_id": "st-escalated", "message": "الخدمة سيئة جدا وما احد رد علي حسبي الله"},
    )
    sessions = client.get("/api/sessions").get_json()["sessions"]
    summary = sessions[0]
    assert summary["status"] == "escalated"
    assert isinstance(summary["ticket_id"], int)


def test_sessions_status_unresolved_when_low_confidence(client):
    """حالة الجلسة = unresolved عند انتهائها بدورة منخفضة الثقة."""
    client.post("/api/chat", json={"session_id": "st-low", "message": "نعم"})
    sessions = client.get("/api/sessions").get_json()["sessions"]
    assert sessions[0]["status"] == "unresolved"


def test_sessions_status_active_for_plain_conversation(client):
    """حالة الجلسة = active لمحادثة عامة بلا استعلام ولا مشكلة (حالة محايدة)."""
    client.post("/api/chat", json={"session_id": "st-active", "message": "هلا والله كيف حالكم اليوم"})
    sessions = client.get("/api/sessions").get_json()["sessions"]
    assert sessions[0]["status"] == "active"


def test_sessions_status_unresolved_when_customer_message_unanswered(client, temp_db):
    """جلسة انتهت برسالة عميل بلا رد (انقطاع) => unresolved."""
    # نُحاكي انقطاعاً: رسالة عميل محفوظة بلا رد وكيل (كما يحدث لو فشل الـ LLM).
    db.add_chat_message("st-abandoned", "customer", "طلبي متأخر وين وصل")

    sessions = client.get("/api/sessions").get_json()["sessions"]
    assert sessions[0]["session_id"] == "st-abandoned"
    assert sessions[0]["status"] == "unresolved"


def test_chat_includes_order_details_for_found_order(client):
    """بطاقة الطلب: `order_details` تُبنى عند وجود طلب فعلي."""
    response = client.post(
        "/api/chat",
        json={"session_id": "od-1", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"},
    )
    body = response.get_json()
    details = body["order_details"]
    assert details is not None
    assert details["order_id"] == 1002
    assert details["product_name"] == "شاحن سريع"
    assert details["status"] == "قيد الشحن"
    assert details["order_date"] == "2026-08-28"
    assert details["expected_delivery"] == "2026-09-08"


def test_chat_order_details_null_without_order(client):
    """لا بطاقة طلب عندما لا يوجد طلب (سؤال سياسة)."""
    response = client.post(
        "/api/chat",
        json={"session_id": "od-2", "message": "ابغى ارجع المنتج لان مو مطابق للمواصفات"},
    )
    assert response.get_json()["order_details"] is None


def test_order_details_persist_in_chat_messages_metadata(client, temp_db):
    """Phase 8: تفاصيل الطلب تُحفظ فعلاً في عمود `metadata` بجدول `chat_messages`."""
    client.post(
        "/api/chat",
        json={"session_id": "od-persist", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"},
    )

    history = db.get_chat_history("od-persist")
    agent_message = [m for m in history if m["sender"] == "agent"][0]
    assert agent_message["metadata"] is not None
    assert agent_message["metadata"]["order_details"]["order_id"] == 1002
    assert agent_message["metadata"]["order_details"]["status"] == "قيد الشحن"
    assert agent_message["order_details"]["product_name"] == "شاحن سريع"

    customer_message = [m for m in history if m["sender"] == "customer"][0]
    assert customer_message["metadata"] is None
    assert customer_message["order_details"] is None


def test_history_endpoint_returns_order_details_for_reload(client):
    """Phase 8: `/api/history/` يُرجع `order_details` حتى تُرسم البطاقة بعد إعادة الفتح."""
    client.post(
        "/api/chat",
        json={"session_id": "od-reload", "message": "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"},
    )

    messages = client.get("/api/history/od-reload").get_json()["messages"]
    agent_message = [m for m in messages if m["sender"] == "agent"][0]
    assert agent_message["order_details"]["order_id"] == 1002
    assert agent_message["order_details"]["status"] == "قيد الشحن"
    assert agent_message["order_details"]["order_date"] == "2026-08-28"
    assert agent_message["metadata"]["order_details"] == agent_message["order_details"]


def test_history_metadata_survives_corrupt_json(client, temp_db):
    """حِمولة JSON تالفة لا تُسقط السجل — تُعاد `metadata` كـ None بدل رفع استثناء."""
    connection = db.get_connection(str(temp_db))
    try:
        connection.execute(
            "INSERT INTO chat_messages (session_id, sender, content, metadata) VALUES (?, ?, ?, ?)",
            ("od-corrupt", "agent", "ردّ قديم", "{ليس JSON صالحاً"),
        )
        connection.commit()
    finally:
        connection.close()

    messages = client.get("/api/history/od-corrupt").get_json()["messages"]
    assert len(messages) == 1
    assert messages[0]["content"] == "ردّ قديم"
    assert messages[0]["metadata"] is None
    assert messages[0]["order_details"] is None


def test_metadata_migration_is_idempotent(client, temp_db):
    """الترحيل آمن عند التكرار: تشغيل init_db مرتين لا يفشل ولا يكرّر العمود."""
    db.init_db(str(temp_db))
    db.init_db(str(temp_db))

    connection = db.get_connection(str(temp_db))
    try:
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)")]
    finally:
        connection.close()
    assert columns.count("metadata") == 1
