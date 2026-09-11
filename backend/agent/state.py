"""تعريف حالة الوكيل (AgentState) المتدفقة بين عقد LangGraph.

مطابق حرفياً لـ docs/ADR.md قسم 8.1.
"""

from typing import TypedDict


class AgentState(TypedDict):
    """الحالة المشتركة التي تمر بين عقد الـ Graph.

    ملاحظات سلوكية مهمة (ليست أخطاءً — مقصودة):

    - **`order_id` «ملتصق» (Sticky):** الحالة تُستَرجع من الذاكرة الدائمة في كل
      دورة لاحقة (راجع `graph.run_turn`). إذا لم تحتوِ رسالة العميل الجديدة على رقم
      طلب، **لا تُطمس** قيمة `order_id` السابقة بـ `None`؛ تبقى كما هي ليتمكن
      العميل من السؤال «ومتى يوصل؟» بلا إعادة ذكر الرقم. يُستبدل الرقم فقط عند
      وجود رقم جديد في الرسالة. التفاصيل في `graph.extract_info`.
    - **`tool_result` و `needs_escalation` «لكل دورة»:** تُصفَّران في بداية كل دورة
      داخل `graph.classify_message` (أول عقدة في كل مسار) لمنع تسرّب نتيجة استعلام
      قديم إلى ردّ لا علاقة له به.
    - **`product_name` ليس ملتصقاً:** يُحدَّث بما تُخرجه الرسالة الحالية فقط.

    الحقول:
        session_id (str): معرّف الجلسة (نفس قيمة `thread_id` في الـ checkpointer).
        customer_message (str): رسالة العميل الأصلية كما وردت.
        normalized_message (str): الرسالة بعد التطبيع عبر `normalize_arabic`.
        category (str): الفئة الناتجة من نموذج RNN.
        order_id (int | None): رقم الطلب المستخرج أو الموروث من دورة سابقة (Sticky).
        product_name (str | None): اسم المنتج المستخرج في الرسالة الحالية.
        tool_result (dict | None): نتيجة أدوات الدورة الحالية (تُصفَّر كل دورة).
        final_response (str): نص الرد النهائي الموجّه للعميل.
        needs_escalation (bool): هل أُنشئت تذكرة في الدورة الحالية (تُصفَّر كل دورة).
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
