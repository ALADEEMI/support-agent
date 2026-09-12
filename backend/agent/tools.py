"""الأدوات الثلاث المتاحة للوكيل: حالة الطلب، السياسات، إنشاء تذكرة.

التوقيعات مطابقة حرفياً لـ docs/ADR.md قسم 7. قواعد صارمة (قسم 7):
- لا تفترض أي أداة نجاح الاستعلام — تتحقق من وجود النتيجة قبل إرجاعها.
- كل أداة مُغلّفة بـ `try/except` وترجع رسالة خطأ منظّمة (لا exception خام).
"""

from database import db

# كلمات تدل على طلب تصعيد صريح من العميل (بصيغتها **بعد التطبيع**: إأآ→ا، ة→ه، ى→ي).
EXPLICIT_ESCALATION_KEYWORDS = (
    "اشتكي",
    "اشكي",
    "شكوي رسمي",
    "سجل شكوي",
    "تسجيل شكوي",
    "افتح تذكره",
    "سجل تذكره",
    "سوي تذكره",
    "انشي تذكره",
    "رفع شكوي",
    "رفع طلب",
    "تصعيد",
)


def has_explicit_escalation_request(message: str) -> bool:
    """يتحقق إن كان العميل يطلب تصعيداً/تذكرة صراحةً.

    المدخلات:
        message (str): رسالة العميل الخام.

    المخرجات:
        bool: `True` إذا وُجدت عبارة طلب صريح، وإلا `False`.

    حالات الفشل:
        لا يرفع استثناءات — أي مدخل غير نصي يعطي `False`.
    """
    if not isinstance(message, str) or not message.strip():
        return False

    from agent.normalizer import normalize_arabic

    normalized = normalize_arabic(message)
    return any(keyword in normalized for keyword in EXPLICIT_ESCALATION_KEYWORDS)


def is_genuine_complaint(message: str) -> bool:
    """يتحقق أن الرسالة «وصف حقيقي» لشكوى لا مجرد رمز محادثة قصير.

    السبب (راجع ADR قسم 8.2): رسائل مثل «نعم» أو «من انت» صُنِّفت أحياناً
    `complaint` بثقة منخفضة، فكانت تُنشئ تذاكر بلا معنى. الشرط هنا هو عدد الكلمات.

    المدخلات:
        message (str): رسالة العميل الخام.

    المخرجات:
        bool: `True` إذا كان عدد كلمات الرسالة >= `config.MIN_COMPLAINT_WORDS`.

    حالات الفشل:
        لا يرفع استثناءات — أي مدخل غير نصي يعطي `False`.
    """
    if not isinstance(message, str) or not message.strip():
        return False

    import config

    return len(message.split()) >= config.MIN_COMPLAINT_WORDS


def should_escalate(message: str, category: str, already_escalated: bool = False) -> tuple[bool, str]:
    """يقرّر إن كان ينبغي إنشاء تذكرة لهذه الرسالة، مع سبب القرار.

    القواعد (ADR قسم 8.2 — «تصعيد مقيّد»):
        1. طلب صريح من العميل (كلمات مثل «اشتكي»/«افتح تذكره») => تصعيد دائماً.
        2. الفئة ليست `complaint` => لا تصعيد.
        3. الرسالة قصيرة جداً (ليست وصفاً حقيقياً) => لا تصعيد.
        4. يوجد تصعيد سابق مفتوح في نفس الجلسة => لا تصعيد لمنع تكرار التذاكر.

    المدخلات:
        message (str): رسالة العميل الخام.
        category (str): الفئة المصنّفة.
        already_escalated (bool): هل أُنشئت تذكرة سابقاً في هذه الجلسة.

    المخرجات:
        tuple[bool, str]: (هل يُنشئ تذكرة؟، سبب القرار).

    حالات الفشل:
        لا يرفع استثناءات.
    """
    if has_explicit_escalation_request(message):
        return True, "explicit_escalation_request"
    if category != "complaint":
        return False, "category_not_complaint"
    if not is_genuine_complaint(message):
        return False, "complaint_too_short"
    if already_escalated:
        return False, "ticket_already_open_in_session"
    return True, "validated_complaint"


def check_order_status(order_id: int) -> dict:
    """يجلب حالة طلب معيّن وموعد التوصيل المتوقع.

    المدخلات:
        order_id (int): رقم الطلب المراد الاستعلام عنه.

    المخرجات:
        dict: عند النجاح `{'found': True, 'order_id': int, 'status': str,
            'product_name': str, 'expected_delivery': str | None}`.
            إذا لم يوجد الطلب `{'found': False, 'order_id': int}`.
            عند فشل الاستعلام `{'found': False, 'order_id': int, 'error': str}`.

    حالات الفشل:
        لا يرفع استثناءات — أي خطأ اتصال بقاعدة البيانات يُعاد كرسالة منظّمة
        في مفتاح `error`.
    """
    try:
        order = db.get_order_with_product(order_id)
    except Exception as exc:
        return {"found": False, "order_id": order_id, "error": f"تعذّر الوصول لقاعدة البيانات: {exc}"}

    if order is None:
        return {"found": False, "order_id": order_id}

    return {
        "found": True,
        "order_id": order["order_id"],
        "status": order["status"],
        "product_name": order["product_name"],
        "expected_delivery": order["expected_delivery"],
    }


def check_policy(policy_type: str) -> dict:
    """يجلب نص سياسة معيّنة وحدّها الزمني.

    المدخلات:
        policy_type (str): نوع السياسة (`return` / `refund` / `shipping`).

    المخرجات:
        dict: عند النجاح `{'found': True, 'policy_type': str, 'description': str,
            'days_limit': int | None}`. إذا لم توجد `{'found': False, 'policy_type': str}`.
            عند الفشل `{'found': False, 'policy_type': str, 'error': str}`.

    حالات الفشل:
        لا يرفع استثناءات — أخطاء قاعدة البيانات تُعاد في مفتاح `error`.
    """
    try:
        policy = db.get_policy(policy_type)
    except Exception as exc:
        return {"found": False, "policy_type": policy_type, "error": f"تعذّر الوصول لقاعدة البيانات: {exc}"}

    if policy is None:
        return {"found": False, "policy_type": policy_type}

    return {
        "found": True,
        "policy_type": policy["policy_type"],
        "description": policy["description"],
        "days_limit": policy["days_limit"],
    }


def create_ticket(session_id: str, message: str, category: str, order_id: int | None) -> dict:
    """يُنشئ تذكرة متابعة للرسالة في جدول `tickets`.

    المدخلات:
        session_id (str): معرّف الجلسة.
        message (str): رسالة العميل الأصلية.
        category (str): الفئة المصنّفة.
        order_id (int | None): رقم الطلب إن وُجد.

    المخرجات:
        dict: عند النجاح `{'created': True, 'ticket_id': int}`.
            عند الفشل `{'created': False, 'error': str}`.

    حالات الفشل:
        لا يرفع استثناءات — أخطاء قاعدة البيانات تُعاد في مفتاح `error`.
    """
    try:
        ticket_id = db.create_ticket(session_id, message, category, order_id)
    except Exception as exc:
        return {"created": False, "error": f"تعذّر إنشاء التذكرة: {exc}"}

    return {"created": True, "ticket_id": ticket_id}
