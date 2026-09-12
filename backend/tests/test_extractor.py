"""اختبارات استخراج `order_id` و `product_name` (ADR قسم 4 و 10).

يعمل الاختبار بلا قاعدة بيانات عند تمرير قائمة المنتجات صراحةً، مع اختبار
إضافي واحد يتحقق من القائمة الفعلية بقاعدة البيانات.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent.extractor import (  # noqa: E402
    extract_info,
    extract_order_id,
    extract_product_name,
    extract_ticket_reference,
    is_policy_question,
)
from agent.normalizer import normalize_arabic  # noqa: E402

PRODUCTS = [
    "سماعة بلوتوث",
    "شاحن سريع",
    "ساعة ذكية",
    "جوال سامسونج",
    "لابتوب ديل",
    "طقم مطبخ",
    "مكواة بخار",
    "مكنسة كهربائية",
    "كرسي مكتب",
    "طاولة قهوة",
    "حذاء رياضي",
    "شنطة ظهر",
    "نظارة شمسية",
    "عطر رجالي",
    "بطانية شتوية",
]


def test_extract_order_id_with_keyword():
    """رقم الطلب يُستخرج عندما يُسبَق بكلمة مفتاحية."""
    assert extract_order_id("وين وصل طلبي رقم 1005 يا اخي؟") == 1005
    assert extract_order_id("الاوردر 1012 متى يوصل؟") == 1012
    assert extract_order_id("رقم الطلب 1003") == 1003


def test_extract_order_id_arabic_indic_digits():
    """الأرقام العربية-الهندية تُحوَّل ثم تُستخرج."""
    assert extract_order_id("طلبي رقم ١٠٠٧ وين وصل") == 1007
    assert extract_order_id("اوردر ١٠١٥") == 1015


def test_extract_order_id_bare_number():
    """رقم من أربع خانات بلا كلمة مفتاحية يُلتقط من النص."""
    assert extract_order_id("1009") == 1009


def test_extract_order_id_returns_none_when_absent():
    """لا رقم طلب في النص => None."""
    assert extract_order_id("السلام عليكم كيف حالكم") is None
    assert extract_order_id("") is None
    assert extract_order_id(None) is None


def test_extract_product_name_exact_and_with_definite_article():
    """مطابقة اسم المنتج تعمل مع وبلا «ال» التعريف."""
    assert extract_product_name("وصلتني سماعة بلوتوث مكسورة", PRODUCTS) == "سماعة بلوتوث"
    assert extract_product_name("الشنطة الظهر تاخرت", PRODUCTS) == "شنطة ظهر"
    assert extract_product_name("اللابتوب ديل فيه مشكلة", PRODUCTS) == "لابتوب ديل"
    assert extract_product_name("ابغى ارجع المكواة البخار", PRODUCTS) == "مكواة بخار"


def test_extract_product_name_with_spelling_variation():
    """المطابقة تعمل مع فروق الإملاء والهمزات بعد التطبيع."""
    assert extract_product_name("وصلتني بطانيه شتويه مخيطه", PRODUCTS) == "بطانية شتوية"
    assert extract_product_name("الساعة الذكية خربت", PRODUCTS) == "ساعة ذكية"
    assert extract_product_name("المكنسة الكهربائية ما تشتغل", PRODUCTS) == "مكنسة كهربائية"


def test_extract_product_name_returns_none_when_absent():
    """لا منتج في النص => None."""
    assert extract_product_name("السلام عليكم ورحمة الله", PRODUCTS) is None


def test_extract_info_combines_both_fields():
    """`extract_info` يجمع رقم الطلب واسم المنتج معاً."""
    result = extract_info("مرحبا، طلبي رقم 1002 وهو شاحن سريع متى يوصل؟", PRODUCTS)
    assert result["order_id"] == 1002
    assert result["product_name"] == "شاحن سريع"


def test_extract_info_uses_database_product_list():
    """عند عدم تمرير قائمة منتجات، تُقرأ القائمة الفعلية من قاعدة البيانات."""
    result = extract_info("وصلني الاوردر 1013 ومعه نظارة شمسية متكسرة")
    assert result["order_id"] == 1013
    assert result["product_name"] == "نظارة شمسية"


def test_extract_order_id_does_not_cut_inside_longer_number():
    """لا يُقتطع جزء من رقم أطول عند غياب كلمة مفتاحية."""
    assert extract_order_id("123456") is None


def test_extract_order_id_known_limit_takes_keyword_number():
    """قيد معروف: أي رقم بعد كلمة مفتاحية يُعتبر رقم طلب حتى لو كان أطول من المعتاد.

    هذا سلوك مقصود ومُوثَّق (لا يوجد تحقق من وجود الرقم بقاعدة البيانات هنا؛
    التحقق يحدث في أداة `check_order_status`).
    """
    assert extract_order_id("رقم العملية 123456") == 123456


def test_normalizer_is_applied_consistently():
    """سلامة مسار التطبيع: النص المطبّع يوحّد الهمزات والتاء المربوطة."""
    assert normalize_arabic("بطانية شتوية") == "بطانيه شتويه"


def test_extract_ticket_reference_detects_explicit_ticket_mentions():
    """كشف رقم التذكرة المذكور صراحةً (Task 3)."""
    assert extract_ticket_reference("ممكن تفاصيل التذكرة 16") == 16
    assert extract_ticket_reference("التذكره 7 وين وصلت") == 7
    assert extract_ticket_reference("رقم التذكرة 123") == 123


def test_extract_ticket_reference_returns_none_without_ticket():
    """لا تذكرة في النص => None."""
    assert extract_ticket_reference("وين وصل طلبي رقم 1002") is None
    assert extract_ticket_reference("نعم") is None
    assert extract_ticket_reference(None) is None


def test_is_policy_question_matches_policy_wording():
    """كشف أسئلة السياسات بالكلمات المفتاحية (Task 4)."""
    assert is_policy_question("ماهي السياسات لديكم") is True
    assert is_policy_question("هلا، عندكم توصيل لمنطقة الرياض؟") is True
    assert is_policy_question("كم مدة الاسترجاع؟") is True
    assert is_policy_question("عندكم ضمان؟") is True


def test_is_policy_question_rejects_order_and_conversation():
    """لا يُصنَّف سؤال الطلب ولا المحادثة العامة كسؤال سياسة."""
    assert is_policy_question("وين وصل طلبي رقم 1002؟") is False
    assert is_policy_question("من انت") is False
    assert is_policy_question("نعم") is False
    assert is_policy_question("") is False
