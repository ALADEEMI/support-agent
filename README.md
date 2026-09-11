# نظام وكيل محادثة لخدمة العملاء — متجر النخبة

وكيل محادثة عربي لخدمة العملاء (لهجة يمنية مهيمنة) لمتجر إلكتروني وهمي، وفق الوثيقة المعتمدة `docs/ADR.md`.

## المكوّنات

- `backend/` — Flask + LangGraph + SQLite + نموذج RNN (BiLSTM)
- `frontend/` — واجهة React
- `training/` — نوتبوك تدريب الموديل وتقارير التقييم (يُشغَّل يدوياً على Google Colab)
- `docs/` — وثيقة الـ ADR

## المتطلبات المسبقة

- Python **3.12** — TensorFlow لا يوفر حزماً لإصدار 3.14 حالياً، لذلك تُنشأ البيئة الافتراضية بـ `py -3.12`
- Node.js 18+ و npm
- git

## الإعداد

### 1) متغيرات البيئة

```powershell
Copy-Item .env.example .env
```

ثم عبّئ القيم داخل `.env` (خصوصاً `COMMANDCODE_API_KEY`). لا يوضع أي مفتاح داخل الكود ولا يُرفع لأي نظام تحكم إصدار.

### 2) بيئة بايثون (Python 3.12)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

### 3) الواجهة الخلفية (Flask)

```powershell
cd backend
python app.py
```

فحص سريع: `http://localhost:5000/health` يجب أن يعيد `{"status": "ok"}`.

### 4) الواجهة الأمامية (React)

```powershell
cd frontend
npm install
npm start
```

## المراحل

حالة تنفيذ المراحل موثّقة في `PROGRESS.md`، وتفصيلها في `docs/ADR.md` قسم 10.
