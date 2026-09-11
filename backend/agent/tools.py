"""الأدوات الثلاث المتاحة للوكيل: حالة الطلب، السياسات، إنشاء تذكرة.

التوقيعات مطابقة حرفياً لـ docs/ADR.md قسم 7. قواعد صارمة (قسم 7):
- لا تفترض أي أداة نجاح الاستعلام — تتحقق من وجود النتيجة قبل إرجاعها.
- كل أداة مُغلّفة بـ `try/except` وترجع رسالة خطأ منظّمة (لا exception خام).
"""

from database import db


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
