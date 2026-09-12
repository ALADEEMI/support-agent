"""تعريف LangGraph: العقد الست والحواف الشرطية (ADR قسم 8.2)، والذاكرة الدائمة.

تسلسل التنفيذ (محدَّث — راجع ADR قسم 8.2):
    START → classify_message → extract_info
        │            (التصنيف؛ والثقة < INTENT_CONFIDENCE_THRESHOLD تجعله `other`)
        │            (extract_info يطبّق سياسة الالتصاق المحدود لرقم الطلب)
        └─ ثم حافة شرطية واحدة:
            ├─ رقم تذكرة مذكور            → craft_response
            ├─ return_request / سياسة      → fetch_policy    → craft_response
            ├─ complaint / تصعيد صريح      → escalate_ticket → craft_response
            ├─ order_inquiry               → fetch_order_status → craft_response
            └─ غير ذلك (other / ثقة منخفضة) → craft_response

كل عقدة تكتب سطر log واحد بصيغة موحدة: `[NODE_NAME] input=... output=...`.

⚠️ ملاحظة تنفيذية (مخالفة لصيغة ADR الحرفية في قسم 8.3): في إصدار
`langgraph-checkpoint-sqlite` المثبّت (3.1.1) تُرجع `SqliteSaver.from_conn_string(...)`
مُدير سياق (context manager) لا كائناً جاهزاً، لذلك لا يصح الإسناد المباشر
`memory = SqliteSaver.from_conn_string(...)`. نستخدم بدلاً منه المُنشئ
`SqliteSaver(sqlite3.connect(...))` وهو يعطي نفس النتيجة (ذاكرة دائمة بملف SQLite).
"""

import json
import sqlite3
from pathlib import Path

import requests
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

import config
from agent import extractor, prompts, tools
from agent.normalizer import normalize_arabic
from agent.state import AgentState
from database import db
from model import rnn_classifier

BACKEND_DIR = Path(__file__).resolve().parents[1]
AGENT_MEMORY_PATH = BACKEND_DIR / "database" / "agent_memory.db"

ORDER_INQUIRY = "order_inquiry"
RETURN_REQUEST = "return_request"
COMPLAINT = "complaint"
OTHER = "other"

_graph = None
_checkpointer = None


def log_node(node_name: str, input_data: dict, output_data: dict) -> None:
    """يكتب سطر log موحّداً لتتبع تنفيذ العقد (traceability).

    المدخلات:
        node_name (str): اسم العقدة.
        input_data (dict): المدخلات المهمة للعقدة.
        output_data (dict): المخرجات المهمة للعقدة.

    المخرجات:
        None (يطبع على الطرفية).

    حالات الفشل:
        لا يرفع استثناءات — أي قيمة غير قابلة للتحويل إلى JSON تُطبع كنص عادي.
    """
    try:
        rendered_input = json.dumps(input_data, ensure_ascii=False)
        rendered_output = json.dumps(output_data, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered_input, rendered_output = str(input_data), str(output_data)
    print(f"[{node_name}] input={rendered_input} output={rendered_output}", flush=True)


def call_llm(messages: list[dict]) -> str:
    """يستدعي مزوّد الـ LLM ويعيد نص الرد.

    المدخلات:
        messages (list[dict]): قائمة رسائل بصيغة OpenAI (`role` + `content`).

    المخرجات:
        str: نص رد الموديل.

    حالات الفشل:
        RuntimeError: إذا كان `COMMANDCODE_API_KEY` غير موجود بالبيئة.
        requests.HTTPError: إذا أعاد المزوّد رمز خطأ HTTP.
        KeyError/ValueError: إذا كان شكل الاستجابة غير متوقع.
    """
    api_key = config.require_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 1.0,
    }
    response = requests.post(config.COMMANDCODE_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def classify_message(state: AgentState) -> dict:
    """يصنّف نية الرسالة عبر التطبيع ثم نموذج RNN.

    تُصفَّر هنا الحقول **المشتقّة لكل دورة** (`tool_result` و `needs_escalation`)
    لأن هذه العقدة أول عقدة في كل مسار، فتفادي تسرّب قيم الدورة السابقة إلى
    الرد الحالي (مثلاً: ذكر حالة طلب قديم في ردّ على رسالة عامة).
    لا يُصفَّر `order_id` لأنه مقصود أن يبقى «ملتصقاً» — راجع `state.py` و`extract_info`.

    المدخلات:
        state (AgentState): الحالة الواردة (تُقرأ `customer_message`).

    المخرجات:
        dict: تحديث الحالة بمفاتيح `normalized_message`, `category`,
            و`tool_result=None`, `needs_escalation=False`.

    حالات الفشل:
        FileNotFoundError: إذا لم تكن ملفات الموديل موجودة.
        Exception: أخطاء التنبؤ من TensorFlow تُرفع كما هي.
    """
    message = state["customer_message"]
    normalized = normalize_arabic(message)
    raw_category, confidence = rnn_classifier.predict(message)

    # Task 1: لا يُعتمد تصنيف منخفض الثقة إطلاقاً — يُحوَّل إلى `other` فتذهب
    # الرسالة إلى ردّ حواري (طلب توضيح) بدل تنفيذ أدوات مبنية على تخمين.
    low_confidence = confidence < config.INTENT_CONFIDENCE_THRESHOLD
    category = OTHER if low_confidence else raw_category

    policy_question = extractor.is_policy_question(message)

    log_node(
        "classify_message",
        {"customer_message": message},
        {
            "raw_category": raw_category,
            "category": category,
            "confidence": round(confidence, 3),
            "threshold": config.INTENT_CONFIDENCE_THRESHOLD,
            "low_confidence": low_confidence,
            "policy_question": policy_question,
        },
    )
    return {
        "normalized_message": normalized,
        "category": category,
        "intent_confidence": confidence,
        "low_confidence": low_confidence,
        "policy_question": policy_question,
        "tool_result": None,
        "needs_escalation": False,
    }


def extract_info(state: AgentState) -> dict:
    """يستخرج رقم الطلب واسم المنتج ورقم التذكرة، ويطبّق سياسة «الالتصاق المحدود».

    **سياسة `order_id` (Task 3 — التصاق محدود بانتهاء):**
        - إذا ذكر العميل **رقم تذكرة** صراحةً (مثل «التذكرة 16») => يُمسح `order_id`
          ولا يُستبدل برقم جديد (سؤال عن تذكرة ليس سؤالاً عن طلب).
        - وإلا إذا ورد **رقم طلب** في الرسالة => يُعتمد فوراً وتُصفَّر عدّاد الالتصاق.
        - وإلا إذا كانت الرسالة **سؤال سياسة** => لا يُستعار رقم قديم (لا معنى له هناك).
        - وإلا إذا كان هناك رقم سابق ولم ينتهِ عمر التصاقه
          (`order_id_sticky_turns < config.MAX_STICKY_ORDER_TURNS`) => يُستعار
          **لدورة واحدة** ثم ينتهي.
        - خلاف ذلك => يُمسح الرقم.

    (ملاحظة: `product_name` **ليس** ملتصقاً — يُحدَّث بما تُخرجه الرسالة الحالية فقط.)

    المدخلات:
        state (AgentState): تُقرأ منها `customer_message`, `order_id`,
            `order_id_sticky_turns`, `policy_question`.

    المخرجات:
        dict: تحديث الحالة بمفاتيح `order_id`, `product_name`, `ticket_reference`,
            `order_id_sticky_turns`.

    حالات الفشل:
        sqlite3.Error: إذا لزمت قراءة قائمة المنتجات من القاعدة وفشلت.
    """
    message = state["customer_message"]
    ticket_reference = extractor.extract_ticket_reference(message)
    fresh_order = extractor.extract_order_id(message)
    previous_order = state.get("order_id")
    previous_turns = state.get("order_id_sticky_turns", 0) or 0
    category = state.get("category", OTHER)

    if ticket_reference is not None:
        order_id, sticky_turns, resolution = None, 0, "ticket_reference_clears_order"
    elif fresh_order is not None:
        order_id, sticky_turns, resolution = fresh_order, 0, "fresh_order_id"
    elif category not in (ORDER_INQUIRY, COMPLAINT):
        # الالتصاق مخصّص للفئتين اللتين تستهلكان رقم الطلب فعلاً؛ أي فئة أخرى
        # (سياسات/إرجاع/محادثة عامة) تُمسح فيها القيمة القديمة فوراً.
        order_id, sticky_turns, resolution = None, 0, "category_does_not_reuse_order"
    elif previous_order is not None and previous_turns < config.MAX_STICKY_ORDER_TURNS:
        order_id, sticky_turns, resolution = previous_order, previous_turns + 1, "sticky_reused"
    else:
        order_id, sticky_turns, resolution = None, 0, "sticky_expired"

    product_name = extractor.extract_product_name(message)

    log_node(
        "extract_info",
        {"customer_message": message, "previous_order_id": previous_order},
        {
            "order_id": order_id,
            "product_name": product_name,
            "ticket_reference": ticket_reference,
            "order_id_sticky": resolution == "sticky_reused",
            "order_id_resolution": resolution,
        },
    )
    return {
        "order_id": order_id,
        "product_name": product_name,
        "ticket_reference": ticket_reference,
        "order_id_sticky_turns": sticky_turns,
    }


def fetch_order_status(state: AgentState) -> dict:
    """ينفّذ أداة `check_order_status` على رقم الطلب المستخرج.

    المدخلات:
        state (AgentState): الحالة الواردة (تُقرأ `order_id`).

    المخرجات:
        dict: تحديث الحالة بمفتاح `tool_result`.

    حالات الفشل:
        لا يرفع استثناءات — فشل الأداة يعود داخل `tool_result`.
    """
    order_id = state.get("order_id")
    if order_id is None:
        result = {"found": False, "note": "لم يُذكر رقم طلب في رسالة العميل."}
    else:
        result = tools.check_order_status(order_id)
    log_node("fetch_order_status", {"order_id": order_id}, {"tool_result": result})
    return {"tool_result": result}


def fetch_policy(state: AgentState) -> dict:
    """ينفّذ أداة `check_policy` للسياسات الثلاث: `return` ثم `refund` ثم `shipping`.

    القرار: تُجلب السياسات معاً في نداء واحد بدل توجيه ديناميكي معقّد، فيحصل الـ LLM
    على سياق كامل. **أُضيفت سياسة `shipping`** لأن أسئلة الشحن/التوصيل كانت تُصنَّف
    `other` فلا تُجلب لها أي سياسة (راجع ADR قسم 8.2 — Task 4).

    المدخلات:
        state (AgentState): الحالة الواردة (لا تُستخدم حقولها هنا).

    المخرجات:
        dict: تحديث الحالة بمفتاح `tool_result` على شكل
            `{'return': {...}, 'refund': {...}, 'shipping': {...}}`.

    حالات الفشل:
        لا يرفع استثناءات — فشل أي أداة يعود داخل نتيجتها.
    """
    result = {
        "return": tools.check_policy("return"),
        "refund": tools.check_policy("refund"),
        "shipping": tools.check_policy("shipping"),
    }
    log_node(
        "fetch_policy",
        {"policy_types": ["return", "refund", "shipping"]},
        {"tool_result": result},
    )
    return {"tool_result": result}


def escalate_ticket(state: AgentState) -> dict:
    """ينشئ تذكرة متابعة **فقط** إذا استوفت الرسالة شروط التصعيد (Task 2).

    لا تُنشئ العقدة تذكرة تلقائياً لمجرد أن الفئة `complaint`: القرار يمرّ عبر
    `tools.should_escalate` (طلب صريح / وصف شكوى حقيقي / لا تذكرة مفتوحة سابقاً).
    عند التخطّي يُعاد `reason` داخل `tool_result` ليعرف الـ LLM أنه **لم** يُسجَّل
    شيء وأن عليه أن يعرض التصعيد بدل ادّعائه.

    المدخلات:
        state (AgentState): تُقرأ منها `session_id`, `customer_message`,
            `category`, `order_id`, `ticket_id`.

    المخرجات:
        dict: تحديث الحالة بمفاتيح `tool_result` و `needs_escalation`
            (و`ticket_id` عند الإنشاء فقط).

    حالات الفشل:
        لا يرفع استثناءات — فشل الأداة يعود داخل `tool_result`.
    """
    allowed, reason = tools.should_escalate(
        state["customer_message"],
        state.get("category", ""),
        already_escalated=state.get("ticket_id") is not None,
    )

    if not allowed:
        result = {"created": False, "skipped": True, "reason": reason}
        log_node(
            "escalate_ticket",
            {
                "session_id": state["session_id"],
                "category": state.get("category"),
                "already_escalated": state.get("ticket_id") is not None,
            },
            {"tool_result": result},
        )
        return {"tool_result": result, "needs_escalation": False}

    result = tools.create_ticket(
        state["session_id"],
        state["customer_message"],
        state["category"],
        state.get("order_id"),
    )
    created = bool(result.get("created"))
    log_node(
        "escalate_ticket",
        {
            "session_id": state["session_id"],
            "category": state.get("category"),
            "order_id": state.get("order_id"),
            "reason": reason,
        },
        {"tool_result": result},
    )
    update = {"tool_result": result, "needs_escalation": created}
    if created:
        update["ticket_id"] = result.get("ticket_id")
    return update


def recent_history(session_id: str, current_message: str, max_messages: int = 6) -> list[dict]:
    """يجلب آخر رسائل المحادثة الدائمة لاستخدامها كذاكرة قصيرة المدى (Task 4).

    يُستثنى **آخر صف** إن كان هو رسالة العميل الحالية (لأن `app.py` يحفظها قبل
    تشغيل الرسم)، مع بقاء السلوك صحيحاً لو لم تكن محفوظة أصلاً (تشغيل الرسم مباشرة).

    المدخلات:
        session_id (str): معرّف الجلسة.
        current_message (str): رسالة العميل الحالية.
        max_messages (int): أقصى عدد رسائل مُعادة (افتراضياً 6 = آخر 3 دورات).

    المخرجات:
        list[dict]: رسائل مرتّبة زمنياً بمفاتيح `sender` و `content`.

    حالات الفشل:
        لا يرفع استثناءات — أي خطأ قراءة يعيد قائمة فارغة.
    """
    try:
        rows = db.get_chat_history(session_id)
    except Exception:  # noqa: BLE001 - الذاكرة القصيرة تحسين لا شرط للتشغيل
        return []

    if rows and rows[-1].get("sender") == "customer" and rows[-1].get("content") == current_message:
        rows = rows[:-1]
    return rows[-max_messages:]


def craft_response(state: AgentState) -> dict:
    """يبني السياق ديناميكياً (مع ذاكرة المحادثة) ويستدعي الـ LLM لتوليد الرد.

    المدخلات:
        state (AgentState): تُقرأ منها `category`, `tool_result`,
            `customer_message`, `session_id`, `low_confidence`.

    المخرجات:
        dict: تحديث الحالة بمفتاح `final_response`.

    حالات الفشل:
        RuntimeError: إذا كان مفتاح الـ API غير موجود.
        requests.HTTPError: إذا فشل استدعاء المزوّد — يُرفع الخطأ كما هو بدل
            إخفائه (ممنوع أي fallback صامت).
    """
    history = recent_history(state["session_id"], state["customer_message"])
    messages = prompts.build_messages(
        state["category"],
        state.get("tool_result"),
        state["customer_message"],
        history=history,
        low_confidence=bool(state.get("low_confidence")),
    )
    response_text = call_llm(messages)
    log_node(
        "craft_response",
        {
            "category": state["category"],
            "tool_result": state.get("tool_result"),
            "history_messages": len(history),
            "low_confidence": bool(state.get("low_confidence")),
        },
        {"final_response": response_text},
    )
    return {"final_response": response_text}


def route_after_extract(state: AgentState) -> str:
    """يحدد العقدة التالية بعد الاستخراج (الحافة الشرطية الوحيدة في الرسم).

    كل دورات المحادثة تمرّ بـ `extract_info` أولاً، لأنه هو الذي يطبّق سياسة
    «الالتصاق المحدود» لرقم الطلب؛ ثم يقرّر هذا المُوجّه المسار:

        1. ذكر رقم تذكرة → `craft_response` (لا استعلام طلب ولا سياسات).
        2. طلب إرجاع، أو سؤال سياسة مؤكَّد نصياً → `fetch_policy`.
        3. شكوى، أو طلب تصعيد صريح → `escalate_ticket` (وهي التي تقرّر الإنشاء أو التخطّي).
        4. استفسار طلب → `fetch_order_status`.
        5. غير ذلك (بما فيه الثقة المنخفضة بلا دليل نصي) → `craft_response`.

    بهذا لا تصل رسالة منخفضة الثقة إلى عقدة تشغيلية، لأن تصنيفها يُحوَّل إلى `other`
    ولا يوجد معها دليل نصي (سياسة/تصعيد صريح/رقم تذكرة).

    المدخلات:
        state (AgentState): تُقرأ منها `category`, `policy_question`,
            `ticket_reference`, `customer_message`.

    المخرجات:
        str: اسم العقدة التالية.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    if state.get("ticket_reference") is not None:
        return "craft_response"

    category = state["category"]
    message = state.get("customer_message", "")

    if category == RETURN_REQUEST or state.get("policy_question"):
        return "fetch_policy"
    if category == COMPLAINT or tools.has_explicit_escalation_request(message):
        return "escalate_ticket"
    if category == ORDER_INQUIRY:
        return "fetch_order_status"
    return "craft_response"


def build_graph(checkpointer=None):
    """يبني ويصرّف (compile) الـ Graph بالعقد والحواف المعتمدة.

    المدخلات:
        checkpointer: كائن الذاكرة الدائمة (مثل `SqliteSaver`)، أو `None`
            لبِناء الرسم بلا ذاكرة (يُستخدم في اختبارات التوجيه).

    المخرجات:
        CompiledStateGraph: الرسم الجاهز للاستدعاء.

    حالات الفشل:
        لا يرفع استثناءات متوقعة بخلاف أخطاء بناء LangGraph.
    """
    builder = StateGraph(AgentState)

    builder.add_node("classify_message", classify_message)
    builder.add_node("extract_info", extract_info)
    builder.add_node("fetch_order_status", fetch_order_status)
    builder.add_node("fetch_policy", fetch_policy)
    builder.add_node("escalate_ticket", escalate_ticket)
    builder.add_node("craft_response", craft_response)

    builder.add_edge(START, "classify_message")
    builder.add_edge("classify_message", "extract_info")
    builder.add_conditional_edges(
        "extract_info",
        route_after_extract,
        ["fetch_order_status", "fetch_policy", "escalate_ticket", "craft_response"],
    )
    builder.add_edge("fetch_order_status", "craft_response")
    builder.add_edge("fetch_policy", "craft_response")
    builder.add_edge("escalate_ticket", "craft_response")
    builder.add_edge("craft_response", END)

    return builder.compile(checkpointer=checkpointer)


def create_checkpointer(memory_path: str | Path | None = None) -> SqliteSaver:
    """ينشئ ذاكرة LangGraph الدائمة على ملف SQLite.

    المدخلات:
        memory_path (str | Path | None): مسار ملف الذاكرة، أو `None` للمسار
            الافتراضي `backend/database/agent_memory.db`.

    المخرجات:
        SqliteSaver: كائن الذاكرة الدائمة.

    حالات الفشل:
        sqlite3.Error: إذا تعذّر إنشاء مجلد الذاكرة أو فتح ملفها.
    """
    path = Path(memory_path) if memory_path else AGENT_MEMORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(connection)


def get_graph():
    """يرجع الـ Graph المُصرَّف مع الذاكرة الدائمة (يُبنى مرة واحدة ويُخزَّن).

    المدخلات:
        لا يوجد.

    المخرجات:
        CompiledStateGraph: الرسم مع `SqliteSaver` كذاكرة.

    حالات الفشل:
        sqlite3.Error: إذا تعذّر فتح ملف الذاكرة.
    """
    global _graph, _checkpointer
    if _graph is None:
        _checkpointer = create_checkpointer()
        _graph = build_graph(_checkpointer)
    return _graph


def initial_state(session_id: str, customer_message: str) -> AgentState:
    """يبني الحالة الابتدائية لأول رسالة في الجلسة.

    المدخلات:
        session_id (str): معرّف الجلسة (نفس `thread_id`).
        customer_message (str): رسالة العميل.

    المخرجات:
        AgentState: الحالة بكل الحقول المطلوبة وقيم ابتدائية فارغة.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return {
        "session_id": session_id,
        "customer_message": customer_message,
        "normalized_message": "",
        "category": "",
        "intent_confidence": 0.0,
        "low_confidence": False,
        "policy_question": False,
        "order_id": None,
        "product_name": None,
        "ticket_reference": None,
        "ticket_id": None,
        "order_id_sticky_turns": 0,
        "tool_result": None,
        "final_response": "",
        "needs_escalation": False,
    }


def turn_input(session_id: str, customer_message: str) -> dict:
    """يبني مُدخل دورة **لاحقة** (غير الأولى) في جلسة قائمة.

    يُمرَّر حقلان فقط، ويُترك الباقي ليسترجعه الـ checkpointer من الحالة السابقة
    تلقائياً (ADR قسم 8.3) — بدل تمرير قيم ابتدائية تطمس ما تعلّمه الوكيل
    (مثل `order_id` الذي ذكره العميل في دورة سابقة).

    المدخلات:
        session_id (str): معرّف الجلسة.
        customer_message (str): رسالة العميل الجديدة.

    المخرجات:
        dict: `{"session_id", "customer_message"}`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return {"session_id": session_id, "customer_message": customer_message}


def run_turn(session_id: str, customer_message: str) -> AgentState:
    """يشغّل دورة محادثة كاملة عبر الـ Graph بنفس `thread_id`.

    في **الدورة الأولى** للجلسة تُمرَّر حالة ابتدائية كاملة (`initial_state`)،
    وفي **الدورات اللاحقة** يُمرَّر مُدخل الدورة فقط (`turn_input`) لتُستَرجع بقية
    الحالة من الذاكرة الدائمة — هذا هو الإصلاح الجذري لاستهلاك الذاكرة فعلياً.

    المدخلات:
        session_id (str): معرّف الجلسة (يُستخدم كـ `thread_id` للذاكرة).
        customer_message (str): رسالة العميل.

    المخرجات:
        AgentState: الحالة النهائية بعد تنفيذ كل العقد.

    حالات الفشل:
        RuntimeError: إذا كان مفتاح الـ API غير موجود.
        requests.HTTPError: إذا فشل استدعاء الـ LLM.
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    has_previous_state = bool(graph.get_state(config).values)
    payload = turn_input(session_id, customer_message) if has_previous_state else initial_state(session_id, customer_message)

    log_node(
        "run_turn",
        {"session_id": session_id, "turn": "follow_up" if has_previous_state else "first"},
        {"restored_from_memory": has_previous_state},
    )
    return graph.invoke(payload, config)
