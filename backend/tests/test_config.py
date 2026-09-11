"""اختبار حلّ المسارات في `config.py` واستقلالها عن مجلد التشغيل (`cwd`).

يتحقق من:
- تحميل `.env` من جذر المشروع (وليس من `cwd` ولا من داخل `backend/`).
- أن مسارات قواعد البيانات/الموديل المطلقة تشير إلى مواقعها الحقيقية.
- أن النتيجة **متطابقة** سواء استُورد `config` من مجلد المشروع أو من أي مجلد آخر.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402

PATH_VARIABLE_NAMES = [
    "DATABASE_PATH",
    "RNN_MODEL_PATH",
    "TOKENIZER_PATH",
    "LABEL_ENCODER_PATH",
    "MODEL_CONFIG_PATH",
]


def test_env_file_is_project_root():
    """ملف `.env` يُحدَّد من موقع config.py لا من مجلد التشغيل."""
    assert config.BACKEND_DIR == BACKEND_DIR
    assert config.PROJECT_ROOT == PROJECT_ROOT
    assert config.ENV_FILE == PROJECT_ROOT / ".env"


def test_path_variables_are_absolute():
    """كل المتغيرات المسارية تُحلّ إلى مسارات مطلقة."""
    for name in PATH_VARIABLE_NAMES:
        value = getattr(config, name)
        assert Path(value).is_absolute(), f"{name} ليس مساراً مطلقاً: {value}"


def test_database_path_points_inside_backend():
    """مسار قاعدة البيانات يشير إلى `backend/database/` تحديداً."""
    assert Path(config.DATABASE_PATH).parent == BACKEND_DIR / "database"
    assert Path(config.DATABASE_PATH).name == "support.db"


def test_model_paths_point_to_real_files():
    """مسارات الموديل الأربعة تشير إلى ملفات حقيقية موجودة فعلاً."""
    for name in ["RNN_MODEL_PATH", "TOKENIZER_PATH", "LABEL_ENCODER_PATH", "MODEL_CONFIG_PATH"]:
        path = Path(getattr(config, name))
        assert path.parent == BACKEND_DIR / "model" / "artifacts", f"{name} في مجلد غير متوقع: {path}"
        assert path.exists(), f"{name} يشير إلى ملف غير موجود: {path}"


def test_paths_are_identical_when_imported_from_another_cwd(tmp_path):
    """التحقق الحقيقي: استيراد `config` من مجلد مختلف تماماً يعطي نفس المسارات.

    يُشغَّل في عملية فرعية (subprocess) بمجلد تشغيل مؤقت، لأن استيراد الوحدة في
    العملية الحالية مخزَّن مؤقتاً ولا يُعيد التقييم.
    """
    script = (
        "import json, config\n"
        "print(json.dumps({\n"
        "    'ENV_FILE': str(config.ENV_FILE),\n"
        "    'DATABASE_PATH': config.DATABASE_PATH,\n"
        "    'RNN_MODEL_PATH': config.RNN_MODEL_PATH,\n"
        "    'TOKENIZER_PATH': config.TOKENIZER_PATH,\n"
        "    'LABEL_ENCODER_PATH': config.LABEL_ENCODER_PATH,\n"
        "    'MODEL_CONFIG_PATH': config.MODEL_CONFIG_PATH,\n"
        "}))\n"
    )

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(BACKEND_DIR)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )

    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["ENV_FILE"] == str(PROJECT_ROOT / ".env")
    assert payload["DATABASE_PATH"] == config.DATABASE_PATH
    assert payload["RNN_MODEL_PATH"] == config.RNN_MODEL_PATH
    assert payload["TOKENIZER_PATH"] == config.TOKENIZER_PATH
    assert payload["LABEL_ENCODER_PATH"] == config.LABEL_ENCODER_PATH
    assert payload["MODEL_CONFIG_PATH"] == config.MODEL_CONFIG_PATH

    for name in PATH_VARIABLE_NAMES:
        assert Path(payload[name]).is_absolute(), f"{name} ليس مطلقاً عند التشغيل من cwd آخر"
        assert Path(payload[name]).exists(), f"{name} لا يشير لملف حقيقي من cwd آخر: {payload[name]}"


def test_relative_env_values_resolve_against_backend(monkeypatch, tmp_path):
    """قيمة نسبية في المتغير تُفسَّر نسبةً إلى `backend/` لا إلى `cwd`."""
    resolved = config.resolve_backend_path("./database/support.db")
    assert resolved == BACKEND_DIR / "database" / "support.db"

    absolute = tmp_path / "custom.db"
    assert config.resolve_backend_path(str(absolute)) == absolute
