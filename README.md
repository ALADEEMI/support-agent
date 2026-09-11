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

### 3) قاعدة البيانات (SQLite)

تُنشأ القاعدة وتُعبّأ ببيانات وهمية حتمية (منتجات، عملاء، طلبات، سياسات) بأمر واحد:

```powershell
cd backend
python database/seed_data.py
```

- المسار الافتراضي: `backend/database/support.db` (يُتحكم به عبر `DATABASE_PATH` في `.env`).
- الأمر آمن للتكرار: يمسح بيانات الجداول ثم يعيد إدخالها بالقيم نفسها في كل مرة (لا يتضاعف شيء).
- الملف الناتج ملف واحد قابل للنسخ، ولا يُرفع إلى git لأنه بيانات مُولَّدة (يمكن إعادة بنائه بالأمر أعلاه).

**محتوى البيانات التجريبية:** 6 عملاء، 15 منتجاً (القائمة المعتمدة)، 15 طلباً بأرقام ثابتة من `1001` إلى `1015`، و3 سياسات (`return`، `refund`، `shipping`).

أرقام الطلبات الصالحة للاختبار موزعة على كل الحالات:

| حالة الطلب | أمثلة أرقام |
|---|---|
| قيد التجهيز | 1001، 1007، 1012 |
| قيد الشحن | 1002، 1005، 1009، 1014 |
| تم التوصيل | 1003، 1006، 1008، 1010، 1013، 1015 |
| ملغي | 1004، 1011 |

أرقام الطلبات غير الموجودة في هذا النطاق تُستخدم لاختبار حالة «الطلب غير موجود».

### 4) الواجهة الخلفية (Flask)

```powershell
cd backend
python app.py
```

فحص سريع: `http://localhost:5000/health` يجب أن يعيد `{"status": "ok"}`.

#### توثيق الـ API

**`POST /api/chat`** — يستقبل رسالة عميل ويعيد رد الوكيل، ويحفظ الطرفين في `chat_messages`.

جسم الطلب (JSON):

| الحقل | النوع | مطلوب | الوصف |
|---|---|---|---|
| `session_id` | string | نعم | معرّف الجلسة (يُستخدم أيضاً كـ `thread_id` لذاكرة الـ Graph) |
| `message` | string | نعم | رسالة العميل |

```json
{ "session_id": "user-123", "message": "وين وصل طلبي رقم 1002؟" }
```

استجابة النجاح (200):

| الحقل | النوع | الوصف |
|---|---|---|
| `session_id` | string | نفس المعرّف المُرسل |
| `reply` | string | رد الوكيل النصي |
| `category` | string | الفئة المصنّفة (`complaint` / `order_inquiry` / `return_request` / `other`) |
| `order_id` | int \| null | رقم الطلب المستخرج |
| `product_name` | string \| null | المنتج المستخرج |
| `needs_escalation` | bool | هل أُنشئت تذكرة |

```json
{
  "session_id": "user-123",
  "reply": "حياك الله يا غالي، طلبك رقم 1002 حالياً قيد الشحن...",
  "category": "order_inquiry",
  "order_id": 1002,
  "product_name": "شاحن سريع",
  "needs_escalation": false
}
```

أخطاء (كلها بصيغة `{"error": "..."}`):

| الرمز | السبب |
|---|---|
| 400 | جسم ليس JSON، أو `session_id`/`message` مفقود أو فارغ |
| 500 | `COMMANDCODE_API_KEY` غير موجود بالبيئة، أو خطأ داخلي |
| 502 | فشل الوصول إلى مزوّد الـ LLM |

مثال (PowerShell، ثلاث رسائل متتالية بنفس الجلسة):

```powershell
$body = @{ session_id = "user-123"; message = "وين وصل طلبي رقم 1002؟" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:5000/api/chat -Method Post -ContentType "application/json" -Body $body
```

> **ملاحظة:** `GET /api/history/<session_id>` (لعرض السجل في الواجهة) يُنفَّذ في Phase 6.

### 5) الواجهة الأمامية (React)

```powershell
cd frontend
npm install
npm start
```

## المراحل

حالة تنفيذ المراحل موثّقة في `PROGRESS.md`، وتفصيلها في `docs/ADR.md` قسم 10.
