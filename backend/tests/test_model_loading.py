"""اختبار تحميل نموذج RNN والتحقق من تنبؤ منطقي (Sanity Check).

تنفيذ صريح لـ ADR قسم 6.1 نقطة 5: يتحقق أن الموديل يُحمَّل بنجاح من
`backend/model/artifacts/` ويعطي تنبؤاً منطقياً على 3 جمل تجريبية ثابتة.

ويضيف كذلك التحقق الإلزامي من **تطابق دالة التطبيع** بين المشروع والنوتبوك
(ADR قسم 6.1 نقطة 4) — نقطة الفشل الصامت الأخطر في المشروع.

لا تُستخدم أي ملفات وهمية (mock): إذا لم تكن ملفات الموديل موجودة يفشل الاختبار
برسالة واضحة بدل تمريره.
"""

import ast
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.sequence import pad_sequences

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ARTIFACTS_DIR = BACKEND_DIR / "model" / "artifacts"
NOTEBOOK_PATH = REPO_ROOT / "training" / "training_notebook.ipynb"
RAW_DATASET_PATH = REPO_ROOT / "training" / "raw_dataset" / "raw_dataset.csv"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent.normalizer import normalize_arabic  # noqa: E402

MODEL_PATH = ARTIFACTS_DIR / "model.keras"
TOKENIZER_PATH = ARTIFACTS_DIR / "tokenizer.pkl"
LABEL_ENCODER_PATH = ARTIFACTS_DIR / "label_encoder.pkl"
CONFIG_PATH = ARTIFACTS_DIR / "config.json"

SANITY_CASES = [
    ("وينه طلبي يا اخي تاخر كثير مب طبيعي", "order_inquiry"),
    ("ابغى استرجع المنتج لان مو مطابق للمواصفات", "return_request"),
    ("هلا، عندكم توصيل لمنطقة الرياض؟", "other"),
]


@pytest.fixture(scope="module")
def artifacts():
    """يحمّل ملفات الموديل الأربعة من `backend/model/artifacts/` مرة واحدة.

    المخرجات:
        dict: مفاتيحها `model`, `tokenizer`, `label_encoder`, `config`.

    حالات الفشل:
        pytest.fail: إذا كان أي ملف مفقود أو فشل تحميله (بلا أي mock).
    """
    missing = [
        str(p) for p in (MODEL_PATH, TOKENIZER_PATH, LABEL_ENCODER_PATH, CONFIG_PATH)
        if not p.exists()
    ]
    if missing:
        pytest.fail(
            "ملفات الموديل مفقودة — لا يمكن إجراء الاختبار (لا تُستخدم ملفات وهمية): "
            + ", ".join(missing)
        )

    with open(TOKENIZER_PATH, "rb") as f:
        tokenizer = pickle.load(f)
    with open(LABEL_ENCODER_PATH, "rb") as f:
        label_encoder = pickle.load(f)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    model = load_model(MODEL_PATH)
    return {
        "model": model,
        "tokenizer": tokenizer,
        "label_encoder": label_encoder,
        "config": config,
    }


def _predict(text: str, artifacts) -> tuple[str, float, np.ndarray]:
    """يتنبأ بفئة النص بعد تطبيعه وتوكنيزه.

    المدخلات:
        text (str): رسالة العميل الخام.
        artifacts (dict): مخرجات fixture `artifacts`.

    المخرجات:
        tuple: (الفئة المتوقعة، الثقة، متجه الاحتمالات).

    حالات الفشل:
        لا يرفع استثناءات متوقعة بخلاف أخطاء الترميز/التنبؤ من TensorFlow.
    """
    config = artifacts["config"]
    normalized = normalize_arabic(text)
    sequence = pad_sequences(
        artifacts["tokenizer"].texts_to_sequences([normalized]),
        maxlen=config["max_len"],
        padding="post",
    )
    probs = artifacts["model"].predict(sequence, verbose=0)[0]
    label = artifacts["label_encoder"].inverse_transform([int(np.argmax(probs))])[0]
    return label, float(np.max(probs)), probs


def test_model_files_exist():
    """يتحقق من وجود الملفات الأربعة بالمسارات المعتمدة (ADR قسم 6.1)."""
    for path in (MODEL_PATH, TOKENIZER_PATH, LABEL_ENCODER_PATH, CONFIG_PATH):
        assert path.exists(), f"ملف مفقود: {path}"


def test_model_loads(artifacts):
    """يتحقق أن الموديل يُحمَّل فعلياً وأن مدخلاته ومخرجاته بالشكل المتوقع."""
    model = artifacts["model"]
    config = artifacts["config"]

    assert model.input_shape[1] == config["max_len"], (
        f"طول المدخل بالموديل {model.input_shape[1]} لا يطابق config.json {config['max_len']}"
    )
    assert model.output_shape[-1] == len(artifacts["label_encoder"].classes_), (
        "عدد مخرجات الموديل لا يطابق عدد الفئات في label_encoder.pkl"
    )
    assert set(config["classes"]) == set(artifacts["label_encoder"].classes_)


def test_sanity_predictions_are_sensible(artifacts):
    """Sanity check (ADR 6.1 نقطة 5): 3 جمل ثابتة يجب أن تُصنَّف تصنيفاً منطقياً."""
    results = []
    for text, expected in SANITY_CASES:
        label, confidence, _ = _predict(text, artifacts)
        results.append((text, expected, label, confidence))
        print(f"\nالرسالة: {text}\n  → المتوقع: {expected} | الفعلي: {label} (ثقة: {confidence:.2f})")

    wrong = [r for r in results if r[1] != r[2]]
    assert not wrong, "تنبؤات غير منطقية: " + "; ".join(
        f"«{t}» → توقع {e} بالفعل {a}" for t, e, a, _ in wrong
    )


def _load_notebook_normalize_arabic():
    """يستخرج دالة `normalize_arabic` من النوتبوك وينفّذها في نطاق معزول.

    المخرجات:
        callable: نفس الدالة كما وردت في `training_notebook.ipynb`.

    حالات الفشل:
        pytest.fail: إذا لم يوجد الملف أو لم تُعثر الدالة داخله.
    """
    if not NOTEBOOK_PATH.exists():
        pytest.fail(f"النوتبوك مفقود: {NOTEBOOK_PATH}")
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if "def normalize_arabic" not in source:
            continue
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "normalize_arabic":
                namespace: dict = {"re": __import__("re")}
                exec(compile(ast.Module(body=[node], type_ignores=[]), "<notebook>", "exec"), namespace)
                return namespace["normalize_arabic"]
    pytest.fail("لم يتم العثور على دالة normalize_arabic داخل النوتبوك")


def test_normalizer_matches_notebook_training_logic():
    """التحقق الفعلي من تطابق التطبيع بين التدريب والاستدلال (ADR 6.1 نقطة 4).

    يقارن مخرجات `agent.normalizer.normalize_arabic` بمخرجات النسخة المستخرجة
    حرفياً من النوتبوك على كل صفوف الداتا سيت بالإضافة إلى حالات حدّية.
    """
    notebook_fn = _load_notebook_normalize_arabic()

    if not RAW_DATASET_PATH.exists():
        pytest.fail(f"ملف الداتا سيت مفقود: {RAW_DATASET_PATH}")
    df = pd.read_csv(RAW_DATASET_PATH, encoding="utf-8-sig")

    mismatches = []
    for text in df["text"].tolist():
        if normalize_arabic(text) != notebook_fn(text):
            mismatches.append(text)
            if len(mismatches) >= 5:
                break

    edge_cases = [
        None, 123, "", "   ", "مرحباااااا", "كتااااب", "إسراء إبراهيم آدم",
        "٢٠٢٤ سنة جديدة", "الطائرة على الطاولة", "وساااااااااام",
    ]
    for case in edge_cases:
        if normalize_arabic(case) != notebook_fn(case):
            mismatches.append(case)

    assert not mismatches, f"اختلاف في التطبيع عن النوتبوك لـ {len(mismatches)} مدخل، أولها: {mismatches[0]!r}"


def test_sanity_predictions_all_classes_supported(artifacts):
    """يتحقق أن كل فئة من الفئات الأربع موجودة في مخرجات المفردات (sanity)."""
    classes = set(artifacts["label_encoder"].classes_)
    assert classes == {"complaint", "order_inquiry", "return_request", "other"}
