"""تعريف LangGraph: العقد الست والحواف الشرطية (ADR قسم 8.2)، والذاكرة الدائمة.

تسلسل التنفيذ:
    START → classify_message
        ├─ order_inquiry  → extract_info → fetch_order_status → craft_response → END
        ├─ return_request → extract_info → fetch_policy       → craft_response → END
        ├─ complaint      → extract_info → escalate_ticket    → craft_response → END
        └─ other          → craft_response                    → END

ملاحظة (تصحيح بموافقة صاحب المشروع): مسار `complaint` يمرّ بـ `extract_info` قبل
`escalate_ticket` حتى يُلتقط `order_id` ويُخزَّن على التذكرة إن ذكره العميل — بدل
تخطّي الاستخراج مباشرة إلى التصعيد.

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

    المدخلات:
        state (AgentState): الحالة الواردة (تُقرأ `customer_message`).

    المخرجات:
        dict: تحديث الحالة بمفاتيح `normalized_message` و `category`.

    حالات الفشل:
        FileNotFoundError: إذا لم تكن ملفات الموديل موجودة.
        Exception: أخطاء التنبؤ من TensorFlow تُرفع كما هي.
    """
    message = state["customer_message"]
    normalized = normalize_arabic(message)
    category, confidence = rnn_classifier.predict(message)
    log_node(
        "classify_message",
        {"customer_message": message},
        {"category": category, "confidence": round(confidence, 3)},
    )
    return {"normalized_message": normalized, "category": category}


def extract_info(state: AgentState) -> dict:
    """يستخرج رقم الطلب واسم المنتج من رسالة العميل.

    المدخلات:
        state (AgentState): الحالة الواردة (تُقرأ `customer_message`).

    المخرجات:
        dict: تحديث الحالة بمفاتيح `order_id` و `product_name`.

    حالات الفشل:
        sqlite3.Error: إذا لزمت قراءة قائمة المنتجات من القاعدة وفشلت.
    """
    info = extractor.extract_info(state["customer_message"])
    log_node(
        "extract_info",
        {"customer_message": state["customer_message"]},
        {"order_id": info["order_id"], "product_name": info["product_name"]},
    )
    return {"order_id": info["order_id"], "product_name": info["product_name"]}


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
    """ينفّذ أداة `check_policy` للسياستين معاً: `return` ثم `refund`.

    القرار (بموافقة صاحب المشروع): تُجلب السياستان في نداء واحد بلا توجيه ديناميكي
    معقّد، لأن الاسترجاع والإرجاع مترابطان واقعياً، فيحصل الـ LLM على سياق كامل.

    المدخلات:
        state (AgentState): الحالة الواردة (لا تُستخدم حقولها هنا).

    المخرجات:
        dict: تحديث الحالة بمفتاح `tool_result` على شكل
            `{'return': {...}, 'refund': {...}}`.

    حالات الفشل:
        لا يرفع استثناءات — فشل أي أداة يعود داخل نتيجتها.
    """
    result = {
        "return": tools.check_policy("return"),
        "refund": tools.check_policy("refund"),
    }
    log_node("fetch_policy", {"policy_types": ["return", "refund"]}, {"tool_result": result})
    return {"tool_result": result}


def escalate_ticket(state: AgentState) -> dict:
    """ينشئ تذكرة متابعة عبر أداة `create_ticket`.

    المدخلات:
        state (AgentState): تُقرأ منها `session_id`, `customer_message`,
            `category`, `order_id`.

    المخرجات:
        dict: تحديث الحالة بمفتاحَي `tool_result` و `needs_escalation`.

    حالات الفشل:
        لا يرفع استثناءات — فشل الأداة يعود داخل `tool_result`.
    """
    result = tools.create_ticket(
        state["session_id"],
        state["customer_message"],
        state["category"],
        state.get("order_id"),
    )
    log_node(
        "escalate_ticket",
        {"session_id": state["session_id"], "category": state["category"], "order_id": state.get("order_id")},
        {"tool_result": result},
    )
    return {"tool_result": result, "needs_escalation": bool(result.get("created"))}


def craft_response(state: AgentState) -> dict:
    """يبني السياق ديناميكياً ويستدعي الـ LLM لتوليد الرد النهائي.

    المدخلات:
        state (AgentState): تُقرأ منها `category`, `tool_result`, `customer_message`.

    المخرجات:
        dict: تحديث الحالة بمفتاح `final_response`.

    حالات الفشل:
        RuntimeError: إذا كان مفتاح الـ API غير موجود.
        requests.HTTPError: إذا فشل استدعاء المزوّد — يُرفع الخطأ كما هو بدل
            إخفائه (ممنوع أي fallback صامت).
    """
    messages = prompts.build_messages(
        state["category"],
        state.get("tool_result"),
        state["customer_message"],
    )
    response_text = call_llm(messages)
    log_node(
        "craft_response",
        {"category": state["category"], "tool_result": state.get("tool_result")},
        {"final_response": response_text},
    )
    return {"final_response": response_text}


def route_after_classify(state: AgentState) -> str:
    """يحدد العقدة التالية بعد التصنيف بناءً على الفئة.

    كل الفئات — بما فيها `complaint` — تمرّ بـ `extract_info` أولاً حتى تُلتقط
    معلومات الطلب إن ذُكرت، ما عدا `other` التي تذهب مباشرة لتوليد الرد.

    المدخلات:
        state (AgentState): تُقرأ منها `category`.

    المخرجات:
        str: اسم العقدة التالية (`extract_info` أو `craft_response`).

    حالات الفشل:
        لا يرفع استثناءات — أي فئة غير معروفة تُوجَّه إلى `craft_response`.
    """
    category = state["category"]
    if category in (ORDER_INQUIRY, RETURN_REQUEST, COMPLAINT):
        return "extract_info"
    return "craft_response"


def route_after_extract(state: AgentState) -> str:
    """يحدد أي عقدة تُنفَّذ بعد الاستخراج بناءً على الفئة.

    المدخلات:
        state (AgentState): تُقرأ منها `category`.

    المخرجات:
        str: `fetch_policy` لطلبات الإرجاع، `escalate_ticket` للشكاوى،
            وإلا `fetch_order_status`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    category = state["category"]
    if category == RETURN_REQUEST:
        return "fetch_policy"
    if category == COMPLAINT:
        return "escalate_ticket"
    return "fetch_order_status"


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
    builder.add_conditional_edges(
        "classify_message",
        route_after_classify,
        ["extract_info", "craft_response"],
    )
    builder.add_conditional_edges(
        "extract_info",
        route_after_extract,
        ["fetch_order_status", "fetch_policy", "escalate_ticket"],
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
        "order_id": None,
        "product_name": None,
        "tool_result": None,
        "final_response": "",
        "needs_escalation": False,
    }


def run_turn(session_id: str, customer_message: str) -> AgentState:
    """يشغّل دورة محادثة كاملة عبر الـ Graph بنفس `thread_id`.

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
    return graph.invoke(
        initial_state(session_id, customer_message),
        {"configurable": {"thread_id": session_id}},
    )
