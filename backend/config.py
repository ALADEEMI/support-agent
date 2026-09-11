"""تحميل متغيرات البيئة والتحقق منها.

يقرأ الإعدادات من ملف `.env` الموجود بجذر المشروع (انظر `.env.example`).
لا توجد أي قيمة افتراضية لمفتاح الـ API — النظام يفشل برسالة واضحة عند غيابه
(انظر `require_api_key`).
"""

import os

from dotenv import load_dotenv

load_dotenv()

COMMANDCODE_API_KEY = os.getenv("COMMANDCODE_API_KEY") or None
LLM_MODEL = os.getenv("LLM_MODEL") or "deepseek/deepseek-v4.1-flash"

DATABASE_PATH = os.getenv("DATABASE_PATH") or "./database/support.db"

RNN_MODEL_PATH = os.getenv("RNN_MODEL_PATH") or "./model/artifacts/model.keras"
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH") or "./model/artifacts/tokenizer.pkl"
LABEL_ENCODER_PATH = os.getenv("LABEL_ENCODER_PATH") or "./model/artifacts/label_encoder.pkl"
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH") or "./model/artifacts/config.json"

FLASK_ENV = os.getenv("FLASK_ENV") or "development"
FLASK_PORT = int(os.getenv("FLASK_PORT") or "5000")


def require_api_key() -> str:
    """يرجع مفتاح CommandCode API أو يفشل برسالة واضحة.

    المخرجات:
        str: قيمة المفتاح.

    حالات الفشل:
        RuntimeError: إذا كان المتغير `COMMANDCODE_API_KEY` غير موجود أو فارغاً.
    """
    if not COMMANDCODE_API_KEY:
        raise RuntimeError(
            "COMMANDCODE_API_KEY غير موجود بالبيئة. "
            "صدّره عبر الطرفية أو ضعه في ملف .env محلي قبل التشغيل."
        )
    return COMMANDCODE_API_KEY
