"""تطبيع النص العامي العربي — نقطة الربط الحرجة بين التدريب والاستدلال.

⚠️ **حرج (ADR قسم 6.1 نقطة 4):** منطق `normalize_arabic` هنا منسوخ **حرفياً** من
`training/training_notebook.ipynb` (خلية التنظيف). أي اختلاف بسيط يكسر دقة النموذج
وقت الاستدلال دون أي رسالة خطأ ظاهرة. يُتحقق من التطابق فعلياً في
`backend/tests/test_model_loading.py::test_normalizer_matches_notebook_training_logic`.
"""

import re


def normalize_arabic(text: str) -> str:
    """تطبيع النص العربي العامي: توحيد الهمزات، التاء المربوطة، الألف المقصورة،
    إزالة التشكيل، إزالة تكرار الحروف الزائد، توحيد الأرقام.

    المدخلات:
        text (str): النص الخام كما كتبه العميل (قد يحتوي تشكيلاً أو أرقاماً عربية-هندية).

    المخرجات:
        str: النص بعد التطبيع. يرجع سلسلة فارغة `""` إذا كان المدخل ليس `str`.

    حالات الفشل:
        لا يرفع استثناءات — أي مدخل غير نصي يُعاد كسلسلة فارغة.
    """
    if not isinstance(text, str):
        return ""

    text = text.strip()

    # إزالة التشكيل (diacritics)
    arabic_diacritics = re.compile(r"[\u0617-\u061A\u064B-\u0652]")
    text = arabic_diacritics.sub("", text)

    # توحيد الهمزات
    text = re.sub(r"[إأآا]", "ا", text)
    # توحيد التاء المربوطة والهاء
    text = re.sub(r"ة", "ه", text)
    # توحيد الألف المقصورة والياء
    text = re.sub(r"ى", "ي", text)
    # توحيد الأرقام العربية-الهندية إلى أرقام إنجليزية
    arabic_indic = "٠١٢٣٤٥٦٧٨٩"
    western = "0123456789"
    text = text.translate(str.maketrans(arabic_indic, western))
    # إزالة تكرار الحروف الزائد (مثال: "ابددد" -> "ابد")
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    # إزالة المسافات الزائدة
    text = re.sub(r"\s+", " ", text).strip()

    return text
