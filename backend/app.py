"""نقطة تشغيل تطبيق Flask.

في المرحلة 0 يحتوي فقط على مسار الفحص `/health` للتأكد من إقلاع الهيكل.
يُستكمل لاحقاً: `/api/chat` (Phase 5) و `/api/history/<session_id>` (Phase 6).
"""

from flask import Flask

import config

app = Flask(__name__)


@app.get("/health")
def health() -> dict:
    """فحص إقلاع الخدمة.

    المخرجات:
        dict: `{"status": "ok"}`.
    """
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_ENV == "development")
