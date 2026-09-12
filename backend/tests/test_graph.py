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
        connection.execute(
            "INSERT INTO policies (policy_type, description, days_limit) VALUES ('shipping', 'التوصيل خلال 3 إلى 7 أيام عمل.', NULL)"
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
    """سيناريو 3: طلب إرجاع => جلب السياسات الثلاث (إرجاع، استرجاع، شحن).

    تحديث مقصود للمواصفة: أُضيفت سياسة `shipping` إلى `fetch_policy` (Task 4).
    """
    state = compiled.invoke(
        graph.initial_state("s3", "ابغى ارجع المنتج لان مو مطابق للمواصفات"),
        {"configurable": {"thread_id": "s3"}},
    )
    assert state["category"] == "return_request"
    assert set(state["tool_result"].keys()) == {"return", "refund", "shipping"}
    assert state["tool_result"]["return"]["found"] is True
    assert state["tool_result"]["return"]["days_limit"] == 14
    assert state["tool_result"]["refund"]["days_limit"] == 7
    assert state["tool_result"]["shipping"]["found"] is True
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


def test_scenario_5_policy_question_fetches_policies(compiled):
    """سيناريو 5: سؤال شحن/توصيل => سياسة الشحن تُجلب فعلاً (Task 4).

    تحديث مقصود للمواصفة: سابقاً كانت هذه الرسالة تُصنَّف `other` فتذهب مباشرة إلى
    `craft_response` بلا أي سياسة، فيخترع الوكيل الإجابة أو يعتذر بلا سبب.
    """
    state = compiled.invoke(
        graph.initial_state("s5", "هلا، عندكم توصيل لمنطقة الرياض؟"),
        {"configurable": {"thread_id": "s5"}},
    )
    assert state["policy_question"] is True
    assert state["tool_result"] is not None
    assert state["tool_result"]["shipping"]["found"] is True
    assert state["needs_escalation"] is False
    assert state["final_response"] == FIXED_REPLY
    print("SCENARIO5", state["category"], state["tool_result"])


def test_scenario_5b_plain_greeting_skips_tools(compiled, temp_db):
    """رسالة ترحيبية بلا أي دليل نصي => بلا أدوات وبلا تصعيد."""
    state = compiled.invoke(
        graph.initial_state("s5b", "هلا والله كيف حالكم اليوم"),
        {"configurable": {"thread_id": "s5b"}},
    )
    assert state["category"] == "other"
    assert state["tool_result"] is None
    assert state["needs_escalation"] is False

    connection = db.get_connection(str(temp_db))
    try:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0
    finally:
        connection.close()


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


def test_sticky_order_id_across_turns(temp_db, stub_llm, tmp_path, monkeypatch):
    """إصلاح الذاكرة: الدورة الثانية تسترجع `order_id` من الجلسة بلا إعادة ذكره."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "sticky_mem.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("sticky-1", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    assert first["category"] == "order_inquiry"
    assert first["order_id"] == 1002

    second = graph.run_turn("sticky-1", "طيب متى يوصل بالضبط؟")
    assert second["category"] == "order_inquiry"
    assert second["order_id"] == 1002, "لم يُسترجع رقم الطلب من الذاكرة"
    assert second["tool_result"]["found"] is True
    assert second["tool_result"]["order_id"] == 1002
    assert second["tool_result"]["status"] == "قيد الشحن"


def test_turn_input_passes_only_new_fields():
    """`turn_input` يمرّر حقلين فقط، فيُستَرجع الباقي من الذاكرة."""
    payload = graph.turn_input("s", "مرحبا")
    assert payload == {"session_id": "s", "customer_message": "مرحبا"}


def test_run_turn_logs_first_then_follow_up(temp_db, stub_llm, tmp_path, monkeypatch, capsys):
    """الدورة الأولى `first` والثانية `follow_up` مع `restored_from_memory=true`."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "mem_log.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    graph.run_turn("log-1", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    first_output = capsys.readouterr().out
    assert '[run_turn] input={"session_id": "log-1", "turn": "first"}' in first_output
    assert '"restored_from_memory": false' in first_output

    graph.run_turn("log-1", "طيب متى يوصل بالضبط؟")
    second_output = capsys.readouterr().out
    assert '[run_turn] input={"session_id": "log-1", "turn": "follow_up"}' in second_output
    assert '"restored_from_memory": true' in second_output


def test_tool_result_does_not_leak_between_turns(temp_db, stub_llm, tmp_path, monkeypatch):
    """نتيجة استعلام دورة سابقة لا تتسرّب إلى دورة لا علاقة لها بالطلبات."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "leak_tool.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("leak-1", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    assert first["tool_result"] is not None

    second = graph.run_turn("leak-1", "هلا والله كيف حالكم اليوم")
    assert second["category"] == "other"
    assert second["tool_result"] is None, "تسرّبت نتيجة استعلام من دورة سابقة"


def test_needs_escalation_does_not_leak_between_turns(temp_db, stub_llm, tmp_path, monkeypatch):
    """تصعيد دورة سابقة لا يبقى صحيحاً في دورة لا تحتاج تصعيداً."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "leak_esc.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("leak-2", "الخدمة سيئة جدا وما احد رد علي حسبي الله")
    assert first["needs_escalation"] is True

    second = graph.run_turn("leak-2", "هلا والله كيف حالكم اليوم")
    assert second["category"] == "other"
    assert second["needs_escalation"] is False, "بقي التصعيد من دورة سابقة"


# ---------------------------------------------------------------------------
# إصلاح المعمار — تغطية الحالات التي فشلت فعلاً في الجلسة الحيّة (Tasks 1-4).
# الأرقام المذكورة في التعليقات مقاسة فعلياً من النموذج (راجع PROGRESS.md).
# ---------------------------------------------------------------------------


def test_task1_low_confidence_conversational_messages_are_downgraded(compiled):
    """Task 1: «من انت» (ثقة 0.506) و«نعم» (0.431) => other بلا أي أثر جانبي."""
    for index, message in enumerate(["من انت", "نعم"]):
        thread = f"t1-{index}"
        state = compiled.invoke(
            graph.initial_state(thread, message),
            {"configurable": {"thread_id": thread}},
        )
        assert state["low_confidence"] is True, f"متوقع ثقة منخفضة لـ {message!r}"
        assert state["intent_confidence"] < config.INTENT_CONFIDENCE_THRESHOLD
        assert state["category"] == "other", f"لم يُحوَّل {message!r} إلى other"
        assert state["tool_result"] is None
        assert state["needs_escalation"] is False
        print("TASK1", message, round(state["intent_confidence"], 3), state["category"])


def test_task1_low_confidence_policy_question_still_fetches_policies(compiled):
    """Task 1 + 4: «ماهي السياسات لديكم» (0.385) => other، لكن هناك دليل نصي فتُجلب السياسات."""
    state = compiled.invoke(
        graph.initial_state("t1-policy", "ماهي السياسات لديكم"),
        {"configurable": {"thread_id": "t1-policy"}},
    )
    assert state["low_confidence"] is True
    assert state["category"] == "other"
    assert state["policy_question"] is True
    assert set(state["tool_result"].keys()) == {"return", "refund", "shipping"}
    assert state["needs_escalation"] is False
    print("TASK1-POLICY", round(state["intent_confidence"], 3), "policies fetched")


def test_task1_high_confidence_order_inquiry_still_reaches_tool(compiled):
    """Task 1: الرسالة عالية الثقة (0.997) تبقى في مسارها التشغيلي الطبيعي."""
    state = compiled.invoke(
        graph.initial_state("t1-hi", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟"),
        {"configurable": {"thread_id": "t1-hi"}},
    )
    assert state["low_confidence"] is False
    assert state["category"] == "order_inquiry"
    assert state["tool_result"]["found"] is True


def test_task2_no_ticket_spam_for_conversational_messages(compiled, temp_db):
    """Task 2: الرسائل الثلاث التي أنشأت تذاكر زائفة في الجلسة الحيّة لا تُنشئ شيئاً الآن."""
    for index, message in enumerate(["نعم", "من انت", "ماهي السياسات لديكم"]):
        thread = f"t2-{index}"
        compiled.invoke(
            graph.initial_state(thread, message),
            {"configurable": {"thread_id": thread}},
        )

    connection = db.get_connection(str(temp_db))
    try:
        created = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    finally:
        connection.close()
    assert created == 0, f"أُنشئت {created} تذكرة زائفة"
    print("TASK2 tickets_created=", created)


def test_task2_explicit_escalation_request_creates_ticket(compiled, temp_db):
    """Task 2: طلب صريح («افتح تذكرة») يُنشئ تذكرة رغم أن ثقة التصنيف منخفضة."""
    state = compiled.invoke(
        graph.initial_state("t2-exp", "افتح تذكرة"),
        {"configurable": {"thread_id": "t2-exp"}},
    )
    assert state["needs_escalation"] is True
    assert state["tool_result"]["created"] is True
    print("TASK2-EXPLICIT", state["tool_result"])


def test_task2_repeated_complaints_create_only_one_ticket(temp_db, stub_llm, tmp_path, monkeypatch):
    """Task 2: شكوى متكررة في نفس الجلسة لا تُنشئ تذكرة ثانية (منع تكرار التذاكر)."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "dedupe_mem.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("t2-dup", "الخدمة سيئة جدا وما احد رد علي حسبي الله")
    assert first["needs_escalation"] is True
    assert first["ticket_id"] is not None

    second = graph.run_turn("t2-dup", "الخدمة سيئة جدا وما احد رد علي حسبي الله")
    assert second["needs_escalation"] is False
    assert second["tool_result"]["skipped"] is True
    assert second["tool_result"]["reason"] == "ticket_already_open_in_session"

    connection = db.get_connection(str(temp_db))
    try:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
    finally:
        connection.close()
    print("TASK2-DEDUPE", first["ticket_id"], second["tool_result"])


def test_task3_ticket_reference_clears_sticky_order(temp_db, stub_llm, tmp_path, monkeypatch):
    """Task 3: ذكر رقم تذكرة يمسح رقم الطلب الملتصق ولا يستعلم عن الطلب القديم."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "ticket_mem.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("t3-ref", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    assert first["order_id"] == 1002

    second = graph.run_turn("t3-ref", "ممكن تفاصيل التذكرة 16")
    assert second["ticket_reference"] == 16
    assert second["order_id"] is None, "بقي رقم الطلب الملتصق بعد ذكر تذكرة"
    assert second["tool_result"] is None, "استُعلم عن الطلب القديم رغم سؤال عن تذكرة"
    assert second["needs_escalation"] is False
    print("TASK3-TICKET", second["ticket_reference"], second["order_id"])


def test_task3_sticky_order_expires_after_one_turn(temp_db, stub_llm, tmp_path, monkeypatch):
    """Task 3: الالتصاق يُستعار دورة واحدة ثم ينتهي."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "expire_mem.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("t3-exp", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    assert first["order_id"] == 1002
    assert first["order_id_sticky_turns"] == 0

    second = graph.run_turn("t3-exp", "طيب متى يوصل بالضبط؟")
    assert second["order_id"] == 1002, "لم تُستعَر القيمة في الدورة التالية مباشرة"
    assert second["order_id_sticky_turns"] == 1

    third = graph.run_turn("t3-exp", "طيب وبعدين؟")
    assert third["order_id"] is None, "لم ينتهِ الالتصاق بعد دورة واحدة"
    assert third["order_id_sticky_turns"] == 0
    print("TASK3-EXPIRE", first["order_id"], second["order_id"], third["order_id"])


def test_task3_policy_turn_does_not_carry_stale_order(temp_db, stub_llm, tmp_path, monkeypatch):
    """Task 3: سؤال سياسة لا يحمل رقم طلب قديم ولا يستعلم عن حالته."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "policy_clear.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    first = graph.run_turn("t3-pol", "وين وصل طلبي رقم 1002 وهو شاحن سريع؟")
    assert first["order_id"] == 1002

    second = graph.run_turn("t3-pol", "ماهي سياسات الإرجاع عندكم؟")
    assert second["policy_question"] is True
    assert second["order_id"] is None
    assert second["tool_result"] is not None and "return" in second["tool_result"]
    assert "status" not in second["tool_result"], "اندسّت حالة الطلب القديم في سياق السياسات"
    print("TASK3-POLICY", second["order_id"], list(second["tool_result"].keys()))


def test_task4_craft_response_includes_conversation_history(temp_db, stub_llm, tmp_path, monkeypatch):
    """Task 4: سياق الـ LLM يحتوي آخر دورات المحادثة (ذاكرة قصيرة المدى)."""
    compiled = graph.build_graph(graph.create_checkpointer(tmp_path / "history_mem.db"))
    monkeypatch.setattr(graph, "get_graph", lambda: compiled)

    db.add_chat_message("t4-hist", "customer", "اشتي ارجع منتج")
    db.add_chat_message("t4-hist", "agent", "سياسة الإرجاع عندنا 14 يوم من الاستلام")

    graph.run_turn("t4-hist", "مش سألتك قبل شوي...؟")

    assert len(stub_llm) == 1
    user_message = stub_llm[0][1]["content"]
    assert "سياق المحادثة السابقة" in user_message
    assert "اشتي ارجع منتج" in user_message
    assert "سياسة الإرجاع عندنا 14 يوم من الاستلام" in user_message
    assert "ثقة التصنيف منخفضة" in user_message
    print("TASK4-HISTORY", "history injected")


def test_task4_system_prompt_forbids_denying_prior_information():
    """Task 4: البرومبت يمنع صراحةً إنكار معلومة قيلت في الدور السابق."""
    from agent import prompts

    assert "ممنوع أن تنكر معلومة" in prompts.SYSTEM_PROMPT
    assert "سياق المحادثة السابقة" in prompts.SYSTEM_PROMPT
