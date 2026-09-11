"""تحميل متغيرات البيئة وحلّ المسارات والتحقق منها.

مبدآن أساسيان (يعملان من أي مجلد تشغيل — لا يعتمدان على `cwd`):

1. **ملف `.env`** يُحمَّل من **جذر المشروع** (المجلد الأعلى لـ `backend/`)، حسب
   ADR قسم 2 الذي يضع `.env.example` في الجذر.
2. **المسارات النسبية** في متغيرات البيئة (`DATABASE_PATH`, `RNN_MODEL_PATH`,
   `TOKENIZER_PATH`, `LABEL_ENCODER_PATH`, `MODEL_CONFIG_PATH`) تُفسَّر نسبةً إلى
   مجلد **`backend/`** تحديداً — لأن `database/` و `model/artifacts/` تقع هناك.

كلاهما مشتقّ من موقع هذا الملف نفسه عبر `Path(__file__).resolve()`.

لا توجد أي قيمة افتراضية لمفتاح الـ API — النظام يفشل برسالة واضحة عند غيابه
(انظر `require_api_key`).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def resolve_backend_path(value: str) -> Path:
    """يحلّ مساراً إلى مسار مطلق نسبةً إلى مجلد `backend/`.

    المدخلات:
        value (str): مسار مطلق أو نسبي.

    المخرجات:
        Path: مسار مطلق (لا يعتمد على `cwd`).

    حالات الفشل:
        لا يرفع استثناءات.
    """
    path = Path(value)
    return path if path.is_absolute() else BACKEND_DIR / path


COMMANDCODE_API_KEY = os.getenv("COMMANDCODE_API_KEY") or None
COMMANDCODE_API_URL = (
    os.getenv("COMMANDCODE_API_URL") or "https://api.commandcode.ai/provider/v1/chat/completions"
)
LLM_MODEL = os.getenv("LLM_MODEL") or "deepseek/deepseek-v4.1-flash"

DATABASE_PATH = str(resolve_backend_path(os.getenv("DATABASE_PATH") or "./database/support.db"))

RNN_MODEL_PATH = str(resolve_backend_path(os.getenv("RNN_MODEL_PATH") or "./model/artifacts/model.keras"))
TOKENIZER_PATH = str(resolve_backend_path(os.getenv("TOKENIZER_PATH") or "./model/artifacts/tokenizer.pkl"))
LABEL_ENCODER_PATH = str(
    resolve_backend_path(os.getenv("LABEL_ENCODER_PATH") or "./model/artifacts/label_encoder.pkl")
)
MODEL_CONFIG_PATH = str(
    resolve_backend_path(os.getenv("MODEL_CONFIG_PATH") or "./model/artifacts/config.json")
)

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
