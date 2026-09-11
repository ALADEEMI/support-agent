"""تعريف حالة الوكيل (AgentState) المتدفقة بين عقد LangGraph.

مطابق حرفياً لـ docs/ADR.md قسم 8.1.
"""

from typing import TypedDict


class AgentState(TypedDict):
    """الحالة المشتركة التي تمر بين عقد الـ Graph.

    الحقول:
        session_id (str): معرّف الجلسة (نفس قيمة `thread_id` في الـ checkpointer).
        customer_message (str): رسالة العميل الأصلية كما وردت.
        normalized_message (str): الرسالة بعد التطبيع عبر `normalize_arabic`.
        category (str): الفئة الناتجة من نموذج RNN.
        order_id (int | None): رقم الطلب المستخرج، أو `None`.
        product_name (str | None): اسم المنتج المستخرج، أو `None`.
        tool_result (dict | None): نتيجة آخر أداة نُفِّذت، أو `None`.
        final_response (str): نص الرد النهائي الموجّه للعميل.
        needs_escalation (bool): هل أُنشئت تذكرة لهذه الرسالة.
    """

    session_id: str
    customer_message: str
    normalized_message: str
    category: str
    order_id: int | None
    product_name: str | None
    tool_result: dict | None
    final_response: str
    needs_escalation: bool
