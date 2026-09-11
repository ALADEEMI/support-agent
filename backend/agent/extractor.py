"""استخراج المعلومات من النص الحر: `order_id` و `product_name`.

الاستراتيجية (ADR قسم 2 و 8.2 — «regex + matching»):
- `order_id`: يُبحث أولاً عن رقم مسبوق بكلمة مفتاحية (طلب/أوردر/order...)،
  وإلا يُؤخذ أول رقم من 4 خانات في النص.
- `product_name`: مطابقة على مستوى الكلمات بعد التطبيع، مع تجريد «ال» التعريف،
  واختيار المنتج صاحب أعلى تطابق.

كل المطابقة تتم على النص **بعد التطبيع** (`normalize_arabic`) لتفادي فروق
الإملاء والهمزات والأرقام العربية-الهندية.
"""

import re

from agent.normalizer import normalize_arabic
from database import db

KEYWORD_ORDER_PATTERN = re.compile(
    r"(?:رقم\s*الطلب|رقم\s*الاوردر|رقم\s*طلبي|رقم|الطلب|طلبي|طلب|اوردر|الاوردر|order)\D{0,12}?(\d{3,6})"
)
BARE_ORDER_PATTERN = re.compile(r"(?<!\d)(\d{4})(?!\d)")

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_token(token: str) -> str:
    """يجرّد «ال» التعريف من كلمة مطبّعة لتسهيل المطابقة.

    المدخلات:
        token (str): كلمة بعد التطبيع.

    المخرجات:
        str: الكلمة بعد إزالة «ال» البادئة إن وُجدت وكان ما بعدها 3 أحرف على الأقل.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    if len(token) > 3 and token.startswith("ال"):
        return token[2:]
    return token


def tokenize(normalized_text: str) -> set[str]:
    """يحوّل نصاً مطبّعاً إلى مجموعة كلمات منظّفة (بلا ترقيم، وبلا «ال» التعريف).

    المدخلات:
        normalized_text (str): نص بعد التطبيع.

    المخرجات:
        set[str]: مجموعة الكلمات.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    cleaned = _NON_WORD.sub(" ", normalized_text)
    return {normalize_token(word) for word in cleaned.split() if word}


def extract_order_id(text: str) -> int | None:
    """يستخرج رقم الطلب من النص الحر.

    المدخلات:
        text (str): رسالة العميل الخام.

    المخرجات:
        int | None: رقم الطلب إذا وُجد، وإلا `None`.

    حالات الفشل:
        لا يرفع استثناءات — أي مدخل غير نصي يعطي `None`.

    ملاحظة: الأرقام المكوّنة من 4 خانات في سياق غير الطلبات (مثل الأسعار)
        قد تُلتقط كرقم طلب — قيد معروف وموثّق.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    normalized = normalize_arabic(text)

    keyword_match = KEYWORD_ORDER_PATTERN.search(normalized)
    if keyword_match:
        return int(keyword_match.group(1))

    bare_match = BARE_ORDER_PATTERN.search(normalized)
    if bare_match:
        return int(bare_match.group(1))

    return None


def extract_product_name(text: str, product_names: list[str] | None = None) -> str | None:
    """يستخرج اسم المنتج من النص الحر عبر مطابقة الكلمات مع قائمة المنتجات.

    المدخلات:
        text (str): رسالة العميل الخام.
        product_names (list[str] | None): قائمة أسماء المنتجات للمطابقة.
            إذا كانت `None` تُقرأ من جدول `products` بقاعدة البيانات.

    المخرجات:
        str | None: اسم المنتج المطابق (بالشكل الرسمي من القائمة)، أو `None`.

    حالات الفشل:
        sqlite3.Error: إذا تعذّرت قراءة قائمة المنتجات من قاعدة البيانات
            (فقط عندما تكون `product_names` هي `None`).

    ملاحظة: عند تطابق كلمة شائعة فقط (مثل «سريع») قد يقع اختيار خاطئ —
        قيد معروف؛ الـ LLM يتحمل الجزء المتبقي من الفهم.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    if product_names is None:
        product_names = [product["product_name"] for product in db.list_products()]

    normalized = normalize_arabic(text)
    message_tokens = tokenize(normalized)
    if not message_tokens:
        return None

    best_name: str | None = None
    best_score = 0
    best_covered = 0

    for name in product_names:
        name_tokens = [token for token in tokenize(normalize_arabic(name)) if len(token) >= 3]
        matched = [token for token in name_tokens if token in message_tokens]
        if not matched:
            continue

        score = len(matched)
        covered = sum(len(token) for token in matched)
        if (score, covered) > (best_score, best_covered):
            best_name, best_score, best_covered = name, score, covered

    return best_name


def extract_info(text: str, product_names: list[str] | None = None) -> dict:
    """يستخرج `order_id` و `product_name` معاً من الرسالة.

    المدخلات:
        text (str): رسالة العميل الخام.
        product_names (list[str] | None): قائمة المنتجات للمطابقة (اختيارية).

    المخرجات:
        dict: مفاتيحها `order_id` (int | None) و `product_name` (str | None).

    حالات الفشل:
        sqlite3.Error: إذا لزمت قراءة المنتجات من القاعدة وفشلت القراءة.
    """
    return {
        "order_id": extract_order_id(text),
        "product_name": extract_product_name(text, product_names),
    }
