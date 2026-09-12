"""نقطة تشغيل تطبيق Flask وتعرّض واجهة الـ backend.

Phase 5: مسار واحد `POST /api/chat` يربط الـ Graph ويحفظ كل رسالة في جدول
`chat_messages` (سجل المحادثة الدائم — منفصل عن ذاكرة الـ checkpointer، راجع
ADR قسم 1.1). مسار `/health` للإقلاع فقط.

`GET /api/history/<session_id>` يُنفَّذ في Phase 6 حسب ADR قسم 10.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

import config
from agent import graph
from database import db

app = Flask(__name__)
CORS(app)


def _error(message: str, status: int):
    """يبني استجابة خطأ منظّمة بصيغة JSON موحدة.

    المدخلات:
        message (str): نص الخطأ الموجّه للمستهلك.
        status (int): رمز حالة HTTP.

    المخرجات:
        tuple: (استجابة Flask، رمز الحالة).

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return jsonify({"error": message}), status


@app.get("/health")
def health() -> dict:
    """فحص إقلاع الخدمة.

    المخرجات:
        dict: `{"status": "ok"}`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return {"status": "ok"}


def _order_details(state: dict) -> dict | None:
    """يستخرج تفاصيل الطلب من نتيجة أدوات الدورة (لبطاقة الطلب في الواجهة).

    المدخلات:
        state (dict): حالة الوكيل بعد تنفيذ الدورة.

    المخرجات:
        dict | None: `order_id`, `product_name`, `status`, `order_date`,
            `expected_delivery` — أو `None` إذا لم يكن هناك طلب موجود فعلاً.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    tool_result = state.get("tool_result")
    if not isinstance(tool_result, dict) or not tool_result.get("found"):
        return None
    if "order_id" not in tool_result or "status" not in tool_result:
        return None
    return {
        "order_id": tool_result.get("order_id"),
        "product_name": tool_result.get("product_name"),
        "status": tool_result.get("status"),
        "order_date": tool_result.get("order_date"),
        "expected_delivery": tool_result.get("expected_delivery"),
    }


def _tool_outcome(tool_result) -> str:
    """يصنّف نتيجة أدوات الدورة إلى مفتاح مختصر لحالة الجلسة.

    المدخلات:
        tool_result (dict | None): نتيجة الأدوات من حالة الوكيل.

    المخرجات:
        str: `order_found`, `order_not_found`, `policy_found`, `policy_missing`,
            `ticket_created`, `ticket_skipped`, أو `none`.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    if not isinstance(tool_result, dict) or not tool_result:
        return "none"

    if "created" in tool_result:
        return "ticket_created" if tool_result.get("created") else "ticket_skipped"

    policy_keys = [key for key in ("return", "refund", "shipping") if key in tool_result]
    if policy_keys:
        found = any(
            isinstance(tool_result[key], dict) and tool_result[key].get("found") for key in policy_keys
        )
        return "policy_found" if found else "policy_missing"

    if "found" in tool_result:
        if tool_result["found"]:
            return "order_found"
        return "order_not_found" if "order_id" in tool_result else "none"

    return "none"


def _record_turn_outcome(session_id: str, state: dict | None = None, had_error: bool = False) -> None:
    """يسجّل مقياس الدورة لحالة الجلسة، دون إسقاط الطلب إن فشل التسجيل.

    المدخلات:
        session_id (str): معرّف الجلسة.
        state (dict | None): حالة الوكيل (أو `None` عند الفشل).
        had_error (bool): هل انتهت الدورة بخطأ.

    المخرجات:
        None.

    حالات الفشل:
        لا يرفع استثناءات — أي فشل يُسجَّل كتحذير فقط (التسجيل تشخيصي، وليس
        شرطاً لنجاح الطلب). أشهر سبب: قاعدة بيانات قديمة بلا جدول `turn_outcomes`.
    """
    try:
        db.record_turn_outcome(
            session_id,
            (state or {}).get("category", "") or "",
            bool((state or {}).get("low_confidence")),
            _tool_outcome((state or {}).get("tool_result")),
            had_error=had_error,
        )
    except Exception:  # noqa: BLE001 - التشخيص لا يجب أن يُسقط الطلب
        app.logger.warning(
            "تعذّر تسجيل مقاييس الدورة (شغّل python database/seed_data.py لإنشاء جدول turn_outcomes)",
            exc_info=True,
        )


@app.post("/api/chat")
def chat():
    """يستقبل رسالة عميل ويعيد رد الوكيل، مع حفظ الطرفين في سجل المحادثة.

    المدخلات (JSON في جسم الطلب):
        session_id (str): معرّف الجلسة (يُستخدم أيضاً كـ `thread_id` لذاكرة الـ Graph).
        message (str): رسالة العميل.

    المخرجات:
        JSON: `{"session_id", "reply", "category", "order_id", "product_name",
            "needs_escalation"}` برمز 200.

    حالات الفشل:
        400: جسم الطلب ليس JSON صالحاً، أو `session_id`/`message` مفقود أو فارغ.
        500: `COMMANDCODE_API_KEY` غير موجود بالبيئة، أو خطأ داخلي غير متوقع.
        502: فشل الاتصال بمزوّد الـ LLM أو أعاد المزوّد خطأ.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("جسم الطلب يجب أن يكون JSON صالحاً.", 400)

    session_id = payload.get("session_id")
    message = payload.get("message")

    if not isinstance(session_id, str) or not session_id.strip():
        return _error("الحقل 'session_id' مطلوب ويجب أن يكون نصاً غير فارغ.", 400)
    if not isinstance(message, str) or not message.strip():
        return _error("الحقل 'message' مطلوب ويجب أن يكون نصاً غير فارغ.", 400)

    session_id = session_id.strip()
    message = message.strip()

    try:
        db.add_chat_message(session_id, "customer", message)
    except Exception as exc:  # noqa: BLE001 - نُعيد خطأ منظّماً بدل استجابة HTML
        app.logger.exception("فشل حفظ رسالة العميل في chat_messages")
        return _error(f"تعذّر حفظ رسالة العميل: {exc}", 500)

    try:
        state = graph.run_turn(session_id, message)
    except RuntimeError as exc:
        app.logger.error("فشل تشغيل الوكيل (إعداد): %s", exc)
        _record_turn_outcome(session_id, had_error=True)
        return _error(str(exc), 500)
    except requests.RequestException as exc:
        app.logger.error("فشل الاتصال بمزوّد الـ LLM: %s", exc)
        _record_turn_outcome(session_id, had_error=True)
        return _error(f"تعذّر الوصول إلى مزوّد الـ LLM: {exc}", 502)
    except Exception as exc:  # noqa: BLE001 - نُعيد خطأ منظّماً بدل استجابة HTML
        app.logger.exception("خطأ غير متوقع أثناء تشغيل الوكيل")
        _record_turn_outcome(session_id, had_error=True)
        return _error(f"خطأ غير متوقع أثناء معالجة الرسالة: {exc}", 500)

    _record_turn_outcome(session_id, state)

    reply = state.get("final_response", "")
    order_details = _order_details(state)

    try:
        db.add_chat_message(
            session_id,
            "agent",
            reply,
            metadata={"order_details": order_details} if order_details else None,
        )
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("فشل حفظ رد الوكيل في chat_messages")
        return _error(f"تعذّر حفظ رد الوكيل: {exc}", 500)

    return (
        jsonify(
            {
                "session_id": session_id,
                "reply": reply,
                "category": state.get("category"),
                "intent_confidence": round(float(state.get("intent_confidence", 0.0)), 3),
                "low_confidence": state.get("low_confidence", False),
                "policy_question": state.get("policy_question", False),
                "order_id": state.get("order_id"),
                "order_id_sticky_turns": state.get("order_id_sticky_turns", 0),
                "product_name": state.get("product_name"),
                "ticket_reference": state.get("ticket_reference"),
                "ticket_id": state.get("ticket_id"),
                "needs_escalation": state.get("needs_escalation", False),
                "order_details": order_details,
            }
        ),
        200,
    )


@app.get("/api/sessions")
def sessions():
    """يرجع ملخّص كل جلسات المحادثة مع حالتها (لسجل المحادثات في الواجهة).

    المخرجات:
        JSON: `{"sessions": [{session_id, first_message, last_message, updated_at,
            message_count, ticket_id, status}, ...]}` برمز 200، مرتّبة بالأحدث أولاً.
        قيم `status`: `escalated` (تذكرة) / `resolved` (تم الحل) /
        `unresolved` (معلقة) / `active` (محادثة عامة بلا استعلام).

    حالات الفشل:
        500: خطأ في قراءة قاعدة البيانات.
    """
    try:
        summaries = db.list_chat_sessions()
    except Exception as exc:  # noqa: BLE001 - نُعيد خطأ منظّماً بدل استجابة HTML
        app.logger.exception("فشل جلب ملخّص الجلسات")
        return _error(f"تعذّر جلب سجل المحادثات: {exc}", 500)

    return jsonify({"sessions": summaries}), 200


@app.get("/api/history/<session_id>")
def history(session_id: str):
    """يرجع سجل المحادثة الدائم لجلسة معيّنة (لعرضه في الواجهة).

    المدخلات:
        session_id (str): معرّف الجلسة (من مسار الـ URL).

    المخرجات:
        JSON: `{"session_id": str, "messages": [{"message_id", "sender",
            "content", "timestamp"}, ...]}` برمز 200. قائمة فارغة إذا لا يوجد سجل.

    حالات الفشل:
        400: معرّف الجلسة فارغ بعد التنظيف.
        500: خطأ في قراءة قاعدة البيانات.
    """
    cleaned = (session_id or "").strip()
    if not cleaned:
        return _error("معرّف الجلسة مطلوب.", 400)

    try:
        messages = db.get_chat_history(cleaned)
    except Exception as exc:  # noqa: BLE001 - نُعيد خطأ منظّماً بدل استجابة HTML
        app.logger.exception("فشل جلب سجل المحادثة")
        return _error(f"تعذّر جلب سجل المحادثة: {exc}", 500)

    return jsonify({"session_id": cleaned, "messages": messages}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_ENV == "development")
