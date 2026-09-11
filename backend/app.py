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
        return _error(str(exc), 500)
    except requests.RequestException as exc:
        app.logger.error("فشل الاتصال بمزوّد الـ LLM: %s", exc)
        return _error(f"تعذّر الوصول إلى مزوّد الـ LLM: {exc}", 502)
    except Exception as exc:  # noqa: BLE001 - نُعيد خطأ منظّماً بدل استجابة HTML
        app.logger.exception("خطأ غير متوقع أثناء تشغيل الوكيل")
        return _error(f"خطأ غير متوقع أثناء معالجة الرسالة: {exc}", 500)

    reply = state.get("final_response", "")

    try:
        db.add_chat_message(session_id, "agent", reply)
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("فشل حفظ رد الوكيل في chat_messages")
        return _error(f"تعذّر حفظ رد الوكيل: {exc}", 500)

    return (
        jsonify(
            {
                "session_id": session_id,
                "reply": reply,
                "category": state.get("category"),
                "order_id": state.get("order_id"),
                "product_name": state.get("product_name"),
                "needs_escalation": state.get("needs_escalation", False),
            }
        ),
        200,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_ENV == "development")
