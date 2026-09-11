"""اختبار الـ Graph كاملاً: التوجيه، العقد، الذاكرة (ADR قسم 8 و 10).

يُستبدَل استدعاء الـ LLM (اعتماد شبكي خارجي) بدالة مُثبَّتة عبر monkeypatch،
لأن الاختبار يجب أن يتحقق من **منطق الرسم** لا من جودة مزوّد خارجي.
ملفات الموديل الحقيقية تُستخدم كما هي بلا أي mock (ADR قسم 6.1).

### السيناريوهات (ADR قسم 10 — تغطي الفئات الأربع + رقم طلب غير موجود + شكوى برقم طلب)

| # | الفئة | السيناريو | المسار المتوقع | الناتج المتوقع |
|---|---|---|---|---|
| 1 | order_inquiry | سؤال عن حالة طلب موجود (1002) | classify → extract → fetch_order_status → craft | `found=True` + حالة «قيد الشحن» |
| 2 | order_inquiry | سؤال عن طلب غير موجود (987654) | classify → extract → fetch_order_status → craft | `found=False` بلا `status` |
| 3 | return_request | رغبة صريحة بإرجاع منتج | classify → extract → fetch_policy → craft | `tool_result` فيه `return` و `refund` |
| 4 | complaint | شكوى بلا رقم طلب | classify → extract → escalate_ticket → craft | `needs_escalation=True` + تذكرة بـ `order_id=None` |
| 5 | other | سؤال عام / تحية | classify → craft | `tool_result=None` |
| 6 | complaint | شكوى **تذكر رقم طلب** (1002) | classify → extract → escalate_ticket → craft | تذكرة بـ `order_id=1002` |

النتائج الفعلية مُتحقَّق منها في الاختبارات أدناه (تُطبع عند التشغيل بـ `-s`).
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from agent import graph  # noqa: E402
from database import db  # noqa: E402

FIXED_REPLY = "أهلاً بك، تم التحقق من طلبك وسنوافيك بالتفاصيل."


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """قاعدة بيانات اختبار معزولة بالطلبات والسياسات اللازمة لتشغيل الـ Graph."""
    db_path = tmp_path / "graph_test.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_path))

    db.init_db(str(db_path))
    connection = db.get_connection(str(db_path))
    try:
        connection.execute("INSERT INTO customers (customer_id, name, phone) VALUES (1, 'عميل اختبار', '000')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (1, 'شاحن سريع')")
        connection.execute("INSERT INTO products (product_id, product_name) VALUES (2, 'لابتوب ديل')")
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
def stub_llm(monkeypatch):
    """يستبدل استدعاء الـ LLM برد ثابت ويرجع قائمة الرسائل المُلتقطة."""
    captured = []

    def fake_call_llm(messages):
        captured.append(messages)
        return FIXED_REPLY

    monkeypatch.setattr(graph, "call_llm", fake_call_llm)
    return captured


@pytest.fixture()
def compiled(temp_db, stub_llm, tmp_path):
    """رسم مُصرَّف بذاكرة SQLite مؤقتة (لا يلمس ملفات المشروع)."""
    checkpointer = graph.create_checkpointer(tmp_path / "memory.db")
    return graph.build_graph(checkpointer)


def test_scenario_1_order_inquiry_existing_order(compiled, capsys):
    """سيناريو 1: استفسار عن طلب موجود => جلب الحالة."""
    state = compiled.invoke(
        graph.initial_state("s1", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "s1"}},
    )
    assert state["category"] == "order_inquiry"
    assert state["order_id"] == 1002
    assert state["product_name"] == "شاحن سريع"
    assert state["tool_result"]["found"] is True
    assert state["tool_result"]["status"] == "قيد الشحن"
    assert state["final_response"] == FIXED_REPLY
    assert state["needs_escalation"] is False
    print("SCENARIO1", state["category"], state["tool_result"])


def test_scenario_2_order_inquiry_missing_order(compiled):
    """سيناريو 2: استفسار عن طلب غير موجود => found=False بلا status.

    ملاحظة: الرقم المستخدم (987654) بلا تكرار ثلاثي للأرقام، لأن التطبيع
    (المطابق للنوتبوك) يطوي أي حرف/رقم مكرر ثلاث مرات فأكثر — راجع
    `test_normalizer_collapses_repeated_digits_limit` أدناه.
    """
    state = compiled.invoke(
        graph.initial_state("s2", "ابغى اعرف حالة الاوردر 987654 لو سمحت"),
        {"configurable": {"thread_id": "s2"}},
    )
    assert state["category"] == "order_inquiry"
    assert state["order_id"] == 987654
    assert state["tool_result"]["found"] is False
    assert "status" not in state["tool_result"]
    assert state["final_response"] == FIXED_REPLY
    print("SCENARIO2", state["category"], state["tool_result"])


def test_scenario_3_return_request_fetches_both_policies(compiled):
    """سيناريو 3: طلب إرجاع => جلب سياسة الإرجاع والاسترجاع معاً."""
    state = compiled.invoke(
        graph.initial_state("s3", "ابغى ارجع المنتج لان مو مطابق للمواصفات"),
        {"configurable": {"thread_id": "s3"}},
    )
    assert state["category"] == "return_request"
    assert set(state["tool_result"].keys()) == {"return", "refund"}
    assert state["tool_result"]["return"]["found"] is True
    assert state["tool_result"]["return"]["days_limit"] == 14
    assert state["tool_result"]["refund"]["days_limit"] == 7
    assert state["final_response"] == FIXED_REPLY
    print("SCENARIO3", state["category"], state["tool_result"])


def test_scenario_4_complaint_creates_ticket(compiled, temp_db):
    """سيناريو 4: شكوى => إنشاء تذكرة وتصعيد."""
    state = compiled.invoke(
        graph.initial_state("s4", "الخدمة سيئة جدا وما احد رد علي حسبي الله"),
        {"configurable": {"thread_id": "s4"}},
    )
    assert state["category"] == "complaint"
    assert state["needs_escalation"] is True
    assert state["tool_result"]["created"] is True
    assert isinstance(state["tool_result"]["ticket_id"], int)

    connection = db.get_connection(str(temp_db))
    try:
        row = connection.execute(
            "SELECT session_id, category FROM tickets WHERE ticket_id = ?",
            (state["tool_result"]["ticket_id"],),
        ).fetchone()
        assert row["session_id"] == "s4"
        assert row["category"] == "complaint"
    finally:
        connection.close()
    print("SCENARIO4", state["category"], state["tool_result"])


def test_scenario_5_other_skips_tools(compiled, temp_db):
    """سيناريو 5: رسالة عامة => لا أدوات ولا تصعيد."""
    state = compiled.invoke(
        graph.initial_state("s5", "هلا، عندكم توصيل لمنطقة الرياض؟"),
        {"configurable": {"thread_id": "s5"}},
    )
    assert state["category"] == "other"
    assert state["tool_result"] is None
    assert state["needs_escalation"] is False
    assert state["final_response"] == FIXED_REPLY

    connection = db.get_connection(str(temp_db))
    try:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0
    finally:
        connection.close()
    print("SCENARIO5", state["category"], state["tool_result"])


def test_scenario_6_complaint_with_order_number_captures_order_id(compiled, temp_db):
    """سيناريو 6: شكوى تذكر رقم طلب => يُلتقط الرقم ويُخزَّن على التذكرة.

    هذا اختبار التصحيح المعتمد: مسار الشكوى يمرّ بـ `extract_info` قبل
    `escalate_ticket` بدل تخطّيه.
    """
    state = compiled.invoke(
        graph.initial_state("s6b", "الطلب رقم 1002 وصل تالف مرتين والخدمة سيئة جدا وما احد رد"),
        {"configurable": {"thread_id": "s6b"}},
    )
    assert state["category"] == "complaint"
    assert state["order_id"] == 1002
    assert state["needs_escalation"] is True
    assert state["tool_result"]["created"] is True

    connection = db.get_connection(str(temp_db))
    try:
        row = connection.execute(
            "SELECT session_id, order_id, category FROM tickets WHERE ticket_id = ?",
            (state["tool_result"]["ticket_id"],),
        ).fetchone()
        assert row["session_id"] == "s6b"
        assert row["order_id"] == 1002
        assert row["category"] == "complaint"
    finally:
        connection.close()
    print("SCENARIO6", state["category"], state["order_id"], state["tool_result"])


def test_complaint_path_runs_extract_info_node(compiled, capsys):
    """مسار الشكوى يمرّ فعلاً بعقدة `extract_info` (تصحيح التوجيه المعتمد)."""
    compiled.invoke(
        graph.initial_state("s6c", "الخدمة سيئة جدا وما احد رد علي حسبي الله"),
        {"configurable": {"thread_id": "s6c"}},
    )
    output = capsys.readouterr().out
    assert "[classify_message] input=" in output
    assert "[extract_info] input=" in output
    assert "[escalate_ticket] input=" in output
    assert "[craft_response] input=" in output


def test_node_logging_format(compiled, capsys):
    """كل عقدة تكتب سطر log واحد بالصيغة الموحدة (ADR قسم 8.2)."""
    compiled.invoke(
        graph.initial_state("s6", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "s6"}},
    )
    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line.startswith("[")]
    assert len(lines) == 4
    assert any(line.startswith("[classify_message] input=") for line in lines)
    assert any(line.startswith("[extract_info] input=") for line in lines)
    assert any(line.startswith("[fetch_order_status] input=") for line in lines)
    assert any(line.startswith("[craft_response] input=") for line in lines)
    for line in lines:
        assert " input=" in line and " output=" in line


def test_checkpointer_keeps_separate_memory_per_session(compiled):
    """الذاكرة تُفصل حسب `thread_id` (نفس `session_id`)."""
    compiled.invoke(
        graph.initial_state("sess-A", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "sess-A"}},
    )
    state_b = compiled.invoke(
        graph.initial_state("sess-B", "هلا، عندكم توصيل لمنطقة الرياض؟"),
        {"configurable": {"thread_id": "sess-B"}},
    )
    stored_a = compiled.get_state({"configurable": {"thread_id": "sess-A"}}).values
    assert stored_a["session_id"] == "sess-A"
    assert stored_a["category"] == "order_inquiry"
    assert state_b["session_id"] == "sess-B"
    assert state_b["category"] == "other"


def test_checkpointer_persists_across_new_graph_instance(temp_db, stub_llm, tmp_path):
    """استمرارية الذاكرة: إعادة بناء الرسم على نفس ملف SQLite تسترجع الحالة."""
    memory_file = tmp_path / "persistent_memory.db"

    first = graph.build_graph(graph.create_checkpointer(memory_file))
    first.invoke(
        graph.initial_state("persist-1", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "persist-1"}},
    )

    second = graph.build_graph(graph.create_checkpointer(memory_file))
    restored = second.get_state({"configurable": {"thread_id": "persist-1"}}).values
    assert restored["category"] == "order_inquiry"
    assert restored["order_id"] == 1002
    assert restored["final_response"] == FIXED_REPLY


def test_normalizer_collapses_repeated_digits_limit():
    """قيد معروف ومُوثَّق: قاعدة «طيّ الحرف المكرر» تُطبَّق على الأرقام أيضاً.

    دالة التطبيع (منسوخة حرفياً من النوتبوك) تستخدم `(.)\\1{2,}`، وهي تطابق أي
    رمز مكرر 3 مرات فأكثر — بما فيها الأرقام. لذلك رقم مثل `999999` يصبح `9`
    قبل الاستخراج. الأثر عملي على أرقام الطلبات الحقيقية (1001–1015) معدوم لأنها
    لا تحتوي تكراراً ثلاثياً، لكنه قيد يجب معرفته عند تسمية أرقام اختبارية.
    """
    from agent.normalizer import normalize_arabic

    assert normalize_arabic("999999") == "9"
    assert normalize_arabic("987654") == "987654"
    assert normalize_arabic("1002") == "1002"


def test_craft_response_uses_dynamic_context(compiled, stub_llm):
    """الـ context يُبنى ديناميكياً من مخرجات العقد السابقة (ADR قسم 9)."""
    compiled.invoke(
        graph.initial_state("s9", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "s9"}},
    )
    assert len(stub_llm) == 1
    system_message, user_message = stub_llm[0]
    assert system_message["role"] == "system"
    assert "متجر النخبة" in system_message["content"]
    assert user_message["role"] == "user"
    assert "order_inquiry" in user_message["content"]
    assert "1002" in user_message["content"]
    assert "وين وصل طلبي رقم 1002" in user_message["content"]
