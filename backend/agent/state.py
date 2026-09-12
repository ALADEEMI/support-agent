"""تعريف حالة الوكيل (AgentState) المتدفقة بين عقد LangGraph.

الحقول الأساسية مطابقة لـ docs/ADR.md قسم 8.1، مع حقول إضافية أُضيفت في
«إصلاح المعمار» (راجع ADR قسم 8.1/8.2 و`PROGRESS.md`)؛ كل حقل جديد له عقدة
واحدة على الأقل تكتبه، ومُغطّى باختبارات.

ملاحظات سلوكية مهمة (ليست أخطاءً — مقصودة):

- **`order_id` «ملتصق» لكنه ينتهي (Bounded Sticky):** يُحتفظ برقم الطلب من دورة
  سابقة **لدورة واحدة فقط** (`order_id_sticky_turns < MAX_STICKY_ORDER_TURNS`)
  حتى يسأل العميل «ومتى يوصل؟» بلا إعادة الرقم. ينتهي الالتصاق بعد ذلك، ويُمسح
  فوراً إذا ذكر العميل رقم تذكرة أو انتقل الحديث إلى السياسات.
- **`tool_result` و `needs_escalation` «لكل دورة»:** تُصفَّران في بداية كل دورة
  داخل `graph.classify_message` لمنع تسرّب نتيجة استعلام قديم إلى ردّ لا علاقة له به.
- **`product_name` ليس ملتصقاً:** يُحدَّث بما تُخرجه الرسالة الحالية فقط.

الحقول:
    session_id (str): معرّف الجلسة (نفس قيمة `thread_id` في الـ checkpointer).
    customer_message (str): رسالة العميل الأصلية كما وردت.
    normalized_message (str): الرسالة بعد التطبيع عبر `normalize_arabic`.
    category (str): الفئة الناتجة من نموذج RNN (أو `other` عند ثقة منخفضة).
    intent_confidence (float): ثقة النموذج في التصنيف (0..1).
    low_confidence (bool): هل الثقة أقل من `config.INTENT_CONFIDENCE_THRESHOLD`.
    policy_question (bool): هل الرسالة سؤال عن سياسة/شروط (كشف بالكلمات المفتاحية).
    order_id (int | None): رقم الطلب المستخرج أو الموروث (Sticky محدود).
    product_name (str | None): اسم المنتج المستخرج في الرسالة الحالية.
    ticket_reference (int | None): رقم تذكرة ذكره العميل صراحةً (يمسح التصاق الطلب).
    ticket_id (int | None): رقم التذكرة المُنشأة في هذه الجلسة (لمنع تكرار التذاكر).
    order_id_sticky_turns (int): عدد الدورات المتتالية التي أُعيد فيها استخدام الرقم.
    tool_result (dict | None): نتيجة أدوات الدورة الحالية (تُصفَّر كل دورة).
    final_response (str): نص الرد النهائي الموجّه للعميل.
    needs_escalation (bool): هل أُنشئت تذكرة في الدورة الحالية (تُصفَّر كل دورة).
"""

from typing import TypedDict


class AgentState(TypedDict):
    """الحالة المشتركة التي تمر بين عقد الـ Graph (انظر docstring الوحدة)."""

    session_id: str
    customer_message: str
    normalized_message: str
    category: str
    intent_confidence: float
    low_confidence: bool
    policy_question: bool
    order_id: int | None
    product_name: str | None
    ticket_reference: int | None
    ticket_id: int | None
    order_id_sticky_turns: int
    tool_result: dict | None
    final_response: str
    needs_escalation: bool
