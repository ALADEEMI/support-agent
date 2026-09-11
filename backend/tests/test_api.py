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
        assert set(message.keys()) == {"message_id", "sender", "content", "timestamp"}


def test_history_is_isolated_per_session(client):
    """سجل كل جلسة مستقل عن غيرها."""
    client.post("/api/chat", json={"session_id": "s-9", "message": "هلا"})
    client.post("/api/chat", json={"session_id": "s-10", "message": "مرحبا"})

    first = client.get("/api/history/s-9").get_json()["messages"]
    second = client.get("/api/history/s-10").get_json()["messages"]
    assert [m["content"] for m in first][0] == "هلا"
    assert [m["content"] for m in second][0] == "مرحبا"
    assert len(first) == len(second) == 2
