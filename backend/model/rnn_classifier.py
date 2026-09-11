"""تحميل نموذج RNN (BiLSTM) والتوكنايزر وتصنيف نية الرسالة.

يتوقع الملفات الأربعة في `backend/model/artifacts/` بالمسارات المعتمدة
(`model.keras`, `tokenizer.pkl`, `label_encoder.pkl`, `config.json` — ADR قسم 6.1).

⚠️ لا تُستخدم أي ملفات وهمية (mock): إذا لم تكن الملفات موجودة أو فشل التحميل
يرفع النظام استثناءً واضحاً بدل تمرير نتيجة عشوائية.

⚠️ التطبيع يُطبَّق هنا عبر `agent.normalizer.normalize_arabic` — نفس الدالة
المستخدمة في التدريب (متحقق منه في `tests/test_model_loading.py`).
"""

import json
import pickle
from pathlib import Path

import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.sequence import pad_sequences

import config
from agent.normalizer import normalize_arabic

BACKEND_DIR = Path(__file__).resolve().parents[1]

_model = None
_tokenizer = None
_label_encoder = None
_model_config = None


def _resolve(path_value: str) -> Path:
    """يحلّ مساراً نسبياً إلى مسار مطلق بالنسبة لمجلد `backend/`.

    المدخلات:
        path_value (str): المسار كما ورد في الإعدادات.

    المخرجات:
        Path: مسار مطلق.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    path = Path(path_value)
    return path if path.is_absolute() else BACKEND_DIR / path


def load_artifacts(force: bool = False) -> None:
    """يحمّل ملفات الموديل الأربعة إلى الذاكرة (مرة واحدة، مع تخزين مؤقت).

    المدخلات:
        force (bool): إذا كانت `True` يُعاد التحميل حتى لو كانت محمّلة.

    المخرجات:
        None.

    حالات الفشل:
        FileNotFoundError: إذا كان أي من الملفات الأربعة مفقوداً (برسالة تذكر
            المسارات الناقصة صراحةً).
        Exception: أي خطأ من TensorFlow/pickle أثناء التحميل يُرفع كما هو.
    """
    global _model, _tokenizer, _label_encoder, _model_config

    if _model is not None and not force:
        return

    paths = {
        "model": _resolve(config.RNN_MODEL_PATH),
        "tokenizer": _resolve(config.TOKENIZER_PATH),
        "label_encoder": _resolve(config.LABEL_ENCODER_PATH),
        "config": _resolve(config.MODEL_CONFIG_PATH),
    }

    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "ملفات الموديل مفقودة — انسخها إلى backend/model/artifacts/ قبل التشغيل: "
            + ", ".join(missing)
        )

    with open(paths["tokenizer"], "rb") as file:
        _tokenizer = pickle.load(file)
    with open(paths["label_encoder"], "rb") as file:
        _label_encoder = pickle.load(file)
    with open(paths["config"], "r", encoding="utf-8") as file:
        _model_config = json.load(file)
    _model = load_model(paths["model"])


def predict(text: str) -> tuple[str, float]:
    """يصنّف رسالة نصية إلى إحدى فئات النية الأربع.

    المدخلات:
        text (str): رسالة العميل الخام (يُطبَّق عليها التطبيع داخلياً).

    المخرجات:
        tuple[str, float]: (الفئة المتوقعة، الثقة بين 0 و 1).

    حالات الفشل:
        FileNotFoundError: إذا لم تكن ملفات الموديل موجودة.
        Exception: أخطاء TensorFlow أثناء التنبؤ تُرفع كما هي.
    """
    load_artifacts()

    normalized = normalize_arabic(text)
    sequence = pad_sequences(
        _tokenizer.texts_to_sequences([normalized]),
        maxlen=_model_config["max_len"],
        padding="post",
    )
    probabilities = _model.predict(sequence, verbose=0)[0]
    index = int(np.argmax(probabilities))
    label = _label_encoder.inverse_transform([index])[0]
    return str(label), float(probabilities[index])


def get_classes() -> list[str]:
    """يرجع ترتيب الفئات كما هو محفوظ في `label_encoder.pkl`.

    المدخلات:
        لا يوجد.

    المخرجات:
        list[str]: أسماء الفئات.

    حالات الفشل:
        FileNotFoundError: إذا لم تكن ملفات الموديل موجودة.
    """
    load_artifacts()
    return [str(name) for name in _label_encoder.classes_]


def is_available() -> bool:
    """يتحقق من وجود ملفات الموديل الأربعة على القرص دون تحميلها.

    المدخلات:
        لا يوجد.

    المخرجات:
        bool: `True` إذا كانت الملفات الأربعة موجودة.

    حالات الفشل:
        لا يرفع استثناءات.
    """
    return all(
        _resolve(path).exists()
        for path in (
            config.RNN_MODEL_PATH,
            config.TOKENIZER_PATH,
            config.LABEL_ENCODER_PATH,
            config.MODEL_CONFIG_PATH,
        )
    )
