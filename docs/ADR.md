# ADR-001: نظام وكيل محادثة لخدمة العملاء (Arabic Dialect Conversational Support Agent)

**الحالة:** معتمد للتنفيذ
**النوع:** Architecture Decision Record + خطة تنفيذ مرحلية (Phased Execution Plan)
**الجمهور:** أي منفذ (إنسان أو AI coding agent) يتولى بناء هذا المشروع

---

## 0. نظرة عامة (Overview)

### 0.1 الهدف
بناء **وكيل محادثة (Conversational Agent)** يعمل كموظف دعم عملاء افتراضي لمتجر إلكتروني وهمي (mock company). الوكيل يستقبل رسائل العملاء **باللهجة العامية العربية** (خليجية/يمنية واقعية)، يصنّف نية الرسالة عبر نموذج RNN مدرّب، يستخرج معلومات رئيسية (رقم الطلب، اسم المنتج)، يستعلم من قاعدة بيانات حقيقية عبر أدوات (Tools) داخل LangGraph، ويرد على العميل بمحادثة طبيعية عبر واجهة React متصلة بـ backend مبني بـ Flask.

### 0.2 المتطلبات الأكاديمية التي يجب أن يحققها المشروع
1. تدريب نموذج RNN (تصنيف نية الرسالة)
2. تحميل ومعالجة داتا سيت غير نظيفة (عامية، أخطاء إملائية، تنوع لغوي)
3. استخراج معلومات (Information Extraction) من النص الحر
4. AI Agent باستخدام LangGraph
5. استخدام System Prompt و Context Engineering بشكل حقيقي وموثّق

### 0.3 نطاق المشروع (Scope) وما هو خارج النطاق
**داخل النطاق:**
- بيانات محاكاة بالكامل (Synthetic/Simulated) — لا بيانات شركة حقيقية
- شركة وهمية واحدة، منتجات محدودة (10-15 منتج) كافية للعرض
- محادثة نصية فقط (لا صوت، لا صور بهذه المرحلة)

**خارج النطاق (مرحلة لاحقة إن وُجدت):**
- ربط ببيانات شركة حقيقية أو تكامل مع أنظمة CRM فعلية
- دعم صوتي أو معالجة صور
- Multi-tenancy (خدمة أكثر من شركة بنفس النظام)
- نشر إنتاجي (Production Deployment) على سيرفر عام

### 0.4 مبدأ التنفيذ الإلزامي (Execution Contract)
> **لكل من ينفّذ هذا الـ ADR (إنسان أو Agent): يُمنع الانتقال من مرحلة (Phase) إلى المرحلة التي تليها قبل الحصول على موافقة صريحة من صاحب المشروع.** عند اكتمال أي Phase، يجب:
> 1. تلخيص ما تم إنجازه فعلياً (لا افتراضات)
> 2. عرض نتائج الاختبار/التحقق الخاصة بهذه المرحلة
> 3. تحديث ملف `PROGRESS.md` بالحالة الجديدة
> 4. **طلب إذن صريح** بالانتقال للمرحلة التالية، والانتظار حتى يُعطى الإذن

---

## 1. المعمار العام (High-Level Architecture)

```
┌──────────────┐   HTTP REST (JSON)   ┌──────────────┐        ┌──────────────┐
│    React      │ ───────────────────► │    Flask      │ ─────► │  SQLite DB    │
│  (Frontend)   │ ◄─────────────────── │  (Backend)    │ ◄───── │  (support.db) │
└──────────────┘                      └──────┬───────┘        └──────────────┘
                                              │
                                              ▼
                                     ┌─────────────────────┐
                                     │   Agent Layer        │
                                     │  (LangGraph Graph)    │
                                     │  - RNN Classifier     │
                                     │  - Extractor          │
                                     │  - Tools (DB access)  │
                                     │  - LLM (via CommandCode)│
                                     │  - Checkpointer (mem)  │
                                     └─────────────────────┘
```

### 1.1 مبدأ الفصل بين "ذاكرة الوكيل" و"سجل المحادثة" (مهم جداً — نقطة كانت غامضة، توضيحها هنا نهائياً)

هذي نقطتين مختلفتين تماماً ولازم نفصل بينهم بوضوح بالتصميم والكود:

| | **Chat History (سجل المحادثة)** | **Agent Memory (ذاكرة الوكيل التنفيذية)** |
|---|---|---|
| **الغرض** | عرض المحادثة للعميل بالواجهة (UI) + أرشفة دائمة | تمكين LangGraph من "تذكر" السياق أثناء التفكير بنفس الجلسة |
| **أين تُخزّن** | جدول `chat_messages` بقاعدة SQLite (دائم) | `MemorySaver` أو `SqliteSaver` الخاص بـ LangGraph (checkpointer) |
| **مدى البقاء** | دائم (Persistent) — يبقى حتى لو أعدت تشغيل السيرفر | يمكن أن يكون بالذاكرة فقط (Ephemeral) أو دائم حسب اختيار الـ checkpointer |
| **المفتاح (Key)** | `customer_id` أو `session_id` | `thread_id` (يُفضّل أن يكون نفس قيمة `session_id`) |
| **من يستخدمها** | الـ Frontend (لعرض الرسائل القديمة عند فتح المحادثة) | الـ Agent Graph فقط (داخلياً، غير مرئي للمستخدم مباشرة) |

**القرار المعماري:** نستخدم **نفس القيمة** لـ `session_id` (بقاعدة البيانات) و `thread_id` (بـ LangGraph checkpointer) — بهذا الشكل، لو انقطع الاتصال ورجع العميل، الـ backend يقدر:
1. يجيب سجل المحادثة القديم من `chat_messages` ويعرضه بالواجهة
2. يمرر نفس `thread_id` لـ LangGraph فيسترجع "حالة تفكيره" (context) تلقائياً

---

## 2. هيكلة الملفات النهائية (Final Directory Structure)

```
support-agent/
│
├── .env.example                 # قالب متغيرات البيئة (بدون قيم حقيقية)
├── PROGRESS.md                  # سجل تتبع تقدّم المراحل (يُحدَّث بعد كل Phase)
├── README.md                    # تعليمات التشغيل الكاملة
│
├── backend/
│   ├── app.py                   # Flask app + endpoints
│   ├── config.py                # تحميل متغيرات البيئة (dotenv)
│   ├── requirements.txt
│   │
│   ├── database/
│   │   ├── db.py                 # اتصال SQLite + دوال CRUD
│   │   ├── schema.sql            # تعريف الجداول
│   │   └── seed_data.py          # تعبئة بيانات وهمية أولية (منتجات، طلبات تجريبية)
│   │
│   ├── agent/
│   │   ├── graph.py               # تعريف LangGraph (nodes + conditional edges)
│   │   ├── state.py               # تعريف AgentState (TypedDict)
│   │   ├── tools.py               # الأدوات الثلاث (check_order_status, check_policy, create_ticket)
│   │   ├── extractor.py           # استخراج order_id / product_name (regex + matching)
│   │   ├── normalizer.py          # تطبيع النص العامي (نفس المنطق المستخدم بالتدريب — critical: يجب تطابقه مع التدريب)
│   │   └── prompts.py             # System prompt + قوالب بناء الـ context
│   │
│   ├── model/
│   │   ├── rnn_classifier.py      # تحميل الموديل + التوكنايزر + دالة predict()
│   │   └── artifacts/             # ⚠️ هنا تُنسخ ملفات الموديل بعد التدريب (انظر قسم 6)
│   │       ├── model.h5
│   │       ├── tokenizer.pkl
│   │       └── label_encoder.pkl
│   │
│   └── tests/
│       ├── test_extractor.py
│       ├── test_tools.py
│       ├── test_graph.py
│       └── test_api.py
│
├── frontend/
│   ├── package.json
│   ├── .env.example              # REACT_APP_API_URL
│   └── src/
│       ├── App.jsx
│       ├── api.js                 # دالة استدعاء /api/chat
│       └── components/
│           └── ChatWindow.jsx
│
├── training/                      # ⚠️ منفصل تماماً عن backend — يُشغَّل مرة واحدة على Colab
│   ├── training_notebook.ipynb    # (الملف الثاني المطلوب — راجع التسليم المستقل)
│   ├── raw_dataset/               # الداتا سيت الخام بعد التوليد
│   └── reports/                   # تقارير التقييم (confusion matrix, classification report)
│
└── docs/
    ├── ADR.md                     # هذا الملف
    └── AGENT_KICKOFF_PROMPT.md    # البرومبت الخاص بتنفيذ المشروع
```

**عدد الملفات الأساسية: ~28 ملف** — كل ملف بمسؤولية واحدة واضحة، لا تكرار، لا تشتت.

---

## 3. متغيرات البيئة (Environment Variables)

**ملف `.env` (لا يُرفع لأي نظام تحكم إصدار — يُضاف لـ `.gitignore`):**

```bash
# مفتاح الوصول لنموذج اللغة عبر CommandCode
COMMANDCODE_API_KEY=

# الموديل المستخدم (مثال)
LLM_MODEL=deepseek/deepseek-v4.1-flash

# مسار قاعدة البيانات
DATABASE_PATH=./database/support.db

# مسارات ملفات الموديل المدرّب (يجب أن تطابق ما ينتجه training_notebook.ipynb)
RNN_MODEL_PATH=./model/artifacts/model.h5
TOKENIZER_PATH=./model/artifacts/tokenizer.pkl
LABEL_ENCODER_PATH=./model/artifacts/label_encoder.pkl

# إعدادات Flask
FLASK_ENV=development
FLASK_PORT=5000
```

**قاعدة صارمة للمُنفّذ (Agent أو مطوّر):**
- **لا يُطلب أو يُفترض أو يُخزَّن مفتاح الـ API داخل الكود مطلقاً.**
- عند بدء التنفيذ الفعلي، يُطلب من صاحب المشروع تزويد المفتاح عبر الطرفية (terminal) مباشرة، مثال:
  ```bash
  export COMMANDCODE_API_KEY="sk-xxxx"
  ```
  أو بوضعه يدوياً داخل ملف `.env` محلي (غير مرفوع)، ثم تحميله عبر `python-dotenv` داخل `config.py`.
- يجب أن يفشل النظام برسالة خطأ واضحة ("COMMANDCODE_API_KEY غير موجود بالبيئة") لو حاول العمل بدون المفتاح — **ممنوع أي fallback صامت أو قيمة افتراضية وهمية.**

---

## 4. قاعدة البيانات (Database Schema)

```sql
-- backend/database/schema.sql

CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('قيد التجهيز', 'قيد الشحن', 'تم التوصيل', 'ملغي')),
    order_date TEXT NOT NULL,
    expected_delivery TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS policies (
    policy_type TEXT PRIMARY KEY,   -- 'return' / 'refund' / 'shipping'
    description TEXT NOT NULL,
    days_limit INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    customer_message TEXT NOT NULL,
    category TEXT NOT NULL,
    order_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved INTEGER DEFAULT 0
);

-- سجل المحادثة الدائم (منفصل عن ذاكرة LangGraph الداخلية — راجع قسم 1.1)
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK (sender IN ('customer', 'agent')),
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tickets_session ON tickets(session_id);
```

**ملاحظة دقيقة:** جدول `chat_messages` أُضيف صراحة هنا (لم يكن مذكوراً بالنقاش السابق) لأنه ضروري لتحقيق "سجل محادثة العميل" المطلوب صراحة — بدونه، لا يوجد مكان لتخزين المحادثة بشكل دائم قابل للعرض بالواجهة عند إعادة فتحها.

---

## 5. استراتيجية الداتا سيت (Dataset Strategy) — تفصيل دقيق

### 5.1 المصدر الأساس
داتا سيت إنجليزي جاهز لتذاكر دعم العملاء (Customer Support Ticket Dataset)، يحتوي أعمدة: نص الرسالة + فئة النية (Complaint / Inquiry / Return Request / Other).

### 5.2 خط أنابيب التوليد (Generation Pipeline)
1. **اختيار عينة** من الداتا سيت الإنجليزي (يُقترح 3000-5000 صف كحد أدنى لضمان تنوع كافٍ لكل فئة)
2. **توليد النسخة العربية العامية** عبر استدعاءات LLM مجمّعة (batched)، باستخدام البرومبت المفصّل بقسم "توليد البيانات" داخل النوتبوك (راجع التسليم الثاني)
3. **حقن التنوع الأسلوبي**: تدوير عدة "أنماط شخصية" بالبرومبت (عميل عصبي/عميل مهذب/عميل مقتضب/عميل يستخدم رموز تعبيرية) لتفادي تكرار نفس القالب اللغوي
4. **حقن أرقام طلبات ومنتجات متسقة**: كل رسالة مولّدة يجب أن تحمل حقلين إضافيين بالميتاداتا (وليس بالضرورة داخل النص): `order_id` و `product_name` عشوائيين من قائمة محددة مسبقاً — هذا يضمن اتساق لاحق مع قاعدة البيانات الفعلية عند الاختبار
5. **إدخال ضوضاء طبيعية إضافية بعد التوليد** (برمجياً، لا عبر LLM): حذف حرف عشوائي بنسبة صغيرة، دمج كلمتين أحياناً، حذف تشكيل إن وُجد

### 5.3 مخطط التصنيف (Label Schema) — نهائي
| الفئة (بالعربي) | الاسم البرمجي | الوصف |
|---|---|---|
| شكوى | `complaint` | تعبير عن استياء دون سؤال محدد |
| استفسار عن طلب | `order_inquiry` | سؤال عن حالة/موعد طلب موجود |
| طلب استرجاع | `return_request` | رغبة صريحة بإرجاع أو استبدال منتج |
| أخرى | `other` | تحية، سؤال عام، غير متعلق بطلب |

### 5.4 معايير الجودة (Quality Gates) — يجب التحقق منها قبل اعتماد الداتا سيت للتدريب
- [ ] توزيع الفئات الأربع متقارب نسبياً (لا فئة تقل عن 15% من الإجمالي) — لو غير متوازن، استخدام `class_weight` بالتدريب
- [ ] مراجعة يدوية لعينة عشوائية 100 صف على الأقل، مع تسجيل نسبة الأخطاء (تصنيف خاطئ أو عامية غير طبيعية)
- [ ] لا تكرار حرفي كامل لأكثر من 1% من الصفوف
- [ ] توثيق عدد الصفوف النهائي، وتوزيع الفئات، بملف `training/reports/dataset_summary.md`

---

## 6. نموذج RNN — التدريب والحفظ (نقطة ربط حرجة بين Colab والمشروع)

### 6.1 المشكلة التي يجب حلّها بوضوح
التدريب يتم على **Google Colab** (بيئة منفصلة تماماً عن المشروع)، بينما الـ backend يحتاج **يحمّل** نفس الموديل محلياً. لذلك:

**خطوات الربط الإلزامية (لا يجوز تخطي أي خطوة):**
1. بعد انتهاء التدريب بـ Colab، يُحفظ الموديل بثلاث ملفات: `model.h5` (أو `.keras`)، `tokenizer.pkl`، `label_encoder.pkl`
2. تُنزَّل الملفات الثلاثة يدوياً من Colab (`files.download()` أو حفظ بـ Google Drive)
3. تُنسخ **حرفياً** إلى المسار: `backend/model/artifacts/`
4. **يجب أن يكون منطق التطبيع (normalization) المستخدم بالتدريب (داخل النوتبوك) مطابقاً تماماً** لملف `backend/agent/normalizer.py` بالمشروع — أي اختلاف بسيط (مثلاً نسيان توحيد الهمزات بأحد الطرفين) يكسر دقة النموذج وقت الاستدلال (inference) دون أي رسالة خطأ ظاهرة. **هذه من أكثر نقاط الفشل الصامتة شيوعاً في مشاريع NLP — يجب اختبارها صراحة بـ Phase 4 (راجع أدناه).**
5. يُكتب اختبار وحدة (`tests/test_model_loading.py`) يتحقق أن الموديل يُحمَّل بنجاح ويعطي تنبؤاً منطقياً على 3 جمل تجريبية ثابتة (sanity check) قبل ربطه بأي شيء آخر.

### 6.2 معمارية النموذج (تفصيل بالنوتبوك، ملخص هنا)
- Embedding (يتدرب من الصفر) → BiLSTM → Dense → Softmax (4 فئات)
- نسخة مقارنة إضافية: Stacked BiLSTM أو GRU، لغرض المقارنة والتقرير (اختياري لكن مطلوب بالنوتبوك حسب طلبك بتدريب أكثر من نموذج)

---

## 7. الأدوات (Tools) — التوقيعات النهائية

```python
def check_order_status(order_id: int) -> dict:
    """يرجع {'found': bool, 'status': str, 'expected_delivery': str} أو {'found': False}"""

def check_policy(policy_type: str) -> dict:
    """يرجع {'found': bool, 'description': str, 'days_limit': int}"""

def create_ticket(session_id: str, message: str, category: str, order_id: int | None) -> dict:
    """يُنشئ صف بجدول tickets، يرجع {'ticket_id': int, 'created': True}"""
```

**قاعدة صارمة:** كل أداة يجب أن:
- لا تفترض نجاح الاستعلام — تتحقق من وجود النتيجة قبل إرجاعها
- تُغلّف بـ `try/except` وترجع رسالة خطأ منظّمة (مو exception خام) عند فشل الاتصال بقاعدة البيانات
- يكون لها اختبار وحدة مستقل بـ `tests/test_tools.py` (باستخدام قاعدة بيانات تجريبية منفصلة، لا قاعدة البيانات الفعلية)

---

## 8. LangGraph — تعريف الحالة والعقد

### 8.1 AgentState

```python
class AgentState(TypedDict):
    session_id: str
    customer_message: str
    normalized_message: str
    category: str              # ناتج RNN
    order_id: int | None        # ناتج extractor
    product_name: str | None    # ناتج extractor
    tool_result: dict | None
    final_response: str
    needs_escalation: bool
```

### 8.2 تسلسل العقد (Nodes) والشروط
راجع الرسم بالنقاش السابق (قسم "LangGraph — الـ Graph الكامل") — يُعتمد كما هو دون تغيير، مع إضافة: كل عقدة (node) تكتب سطر log واحد بصيغة موحدة (`[NODE_NAME] input=... output=...`) لتسهيل التتبع (traceability) أثناء الاختبار.

### 8.3 الذاكرة (Checkpointer)
```python
from langgraph.checkpoint.sqlite import SqliteSaver
memory = SqliteSaver.from_conn_string("./database/agent_memory.db")
```
**قرار:** استخدام `SqliteSaver` لا `MemorySaver` — لأن `MemorySaver` يفقد الحالة عند إعادة تشغيل السيرفر، بينما مشروعنا يحتاج ذاكرة تصمد (متسقة مع كون `chat_messages` أيضاً دائمة بقاعدة البيانات).

---

## 9. System Prompt & Context Engineering — النسخة النهائية المعتمدة

```
أنت "سارة"، موظفة دعم عملاء افتراضية بمتجر [اسم المتجر الوهمي].
- ردّك دائماً باللهجة العامية المهذبة، طبيعية وودودة، لا فصحى جامدة.
- لا تخترع أي معلومة غير موجودة بالسياق المزوّد لك أدناه.
- إذا لم تتوفر معلومة كافية بالسياق، اطلب من العميل التوضيح بدل التخمين.
- إذا كانت الرسالة شكوى ولم تُحل عبر الأدوات المتاحة، أخبر العميل أنك سجّلت الموضوع للمتابعة.

السياق المتاح لهذا الرد:
- نية الرسالة المصنّفة: {category}
- نتيجة الاستعلام (إن وُجدت): {tool_result}
- رسالة العميل الأصلية: {customer_message}
```

**Context Engineering الفعلي هنا:** الحقول الثلاثة بالسياق (`category`, `tool_result`, `customer_message`) **تُبنى ديناميكياً بكل استدعاء** من مخرجات عقد سابقة بالـ Graph — هذا هو التوثيق المطلوب لإثبات أن "بناء السياق" جزء هندسي حقيقي بالمشروع، لا مجرد نص ثابت.

---

## 10. المراحل التنفيذية (Phases) — التفصيل الكامل الملزم

> **تذكير:** بعد كل Phase، توقف واطلب الإذن الصريح بالانتقال للتالية. حدّث `PROGRESS.md` بصيغة: `[x] Phase N — تاريخ الإنجاز — ملاحظات`.

### Phase 0 — الإعداد الأساسي (Bootstrap)
- **البناء:** إنشاء هيكلة المجلدات كاملة (قسم 2)، `requirements.txt`، `.env.example`، `README.md` أولي، تهيئة git + `.gitignore` (يشمل `.env`, `*.h5`, `__pycache__`, `node_modules`)
- **الفحص:** التأكد أن `pip install -r requirements.txt` يعمل بدون أخطاء ببيئة نظيفة
- **التوثيق:** `README.md` يحتوي خطوات التشغيل المحلي كاملة
- **معيار الإنجاز:** المجلد جاهز فارغ المحتوى لكن قابل للتشغيل الهيكلي (skeleton) بدون أخطاء استيراد

### Phase 1 — توليد وتنظيف الداتا سيت
- **البناء:** تنفيذ خط أنابيب التوليد (قسم 5.2) داخل النوتبوك، تطبيق التطبيع، تطبيق معايير الجودة (قسم 5.4)
- **الفحص:** التحقق من كل نقطة بقائمة "معايير الجودة"، تقرير `dataset_summary.md`
- **التوثيق:** توثيق البرومبت المستخدم بالضبط + عدد الاستدعاءات + التكلفة التقريبية (عدد التوكنز) بملف منفصل `training/reports/generation_log.md`
- **معيار الإنجاز:** ملف CSV نهائي معتمد، موقّع بمراجعة يدوية موثقة

### Phase 2 — تدريب وتقييم نموذج RNN
- **البناء:** تنفيذ كامل النوتبوك (تدريب نموذج أو أكثر، مقارنة)
- **الفحص:** classification report + confusion matrix لكل نموذج مُجرَّب، اختيار الأفضل بمبرر مكتوب
- **التوثيق:** `training/reports/model_comparison.md`
- **معيار الإنجاز:** ملفات الموديل الثلاثة جاهزة ومنسوخة لمسارها الصحيح (قسم 6.1)، واختبار Sanity Check ناجح

### Phase 3 — قاعدة البيانات
- **البناء:** `schema.sql` + `seed_data.py` (منتجات، عملاء تجريبيين، طلبات تجريبية، سياسات)
- **الفحص:** استعلامات تجريبية يدوية تتحقق من كل جدول
- **التوثيق:** ملاحظة بـ README عن كيفية إعادة تعبئة البيانات التجريبية
- **معيار الإنجاز:** قاعدة بيانات SQLite جاهزة بملف واحد قابل للنسخ

### Phase 4 — طبقة الوكيل (Extractor + Tools + Graph) بدون واجهة
- **البناء:** `normalizer.py`، `extractor.py`، `tools.py`، `graph.py`، `state.py`، `prompts.py`
- **الفحص (حرج):** اختبار مطابقة التطبيع بين التدريب والاستدلال (قسم 6.1 نقطة 4) — **إلزامي وليس اختيارياً**، اختبار الـ Graph كاملاً عبر `terminal` بمحادثة تجريبية يدوية (5 سيناريوهات على الأقل تغطي الفئات الأربع)
- **التوثيق:** أمثلة الاختبار الخمسة موثقة بـ `backend/tests/test_graph.py` مع النتائج المتوقعة والفعلية
- **معيار الإنجاز:** الوكيل يعمل بالكامل عبر سكربت بايثون مباشر، بدون Flask أو React بعد

### Phase 5 — Flask Backend
- **البناء:** `app.py` (endpoint وحيد `/api/chat`)، تحميل متغيرات البيئة عبر `config.py`، ربط الـ Graph، حفظ كل رسالة بجدول `chat_messages`
- **الفحص:** اختبار عبر `curl` أو `Postman` لعدة رسائل متتالية بنفس `session_id`، التحقق من استمرارية الذاكرة
- **التوثيق:** توثيق شكل الـ request/response بـ README (JSON schema)
- **معيار الإنجاز:** endpoint يعمل ويحافظ على الذاكرة بين الطلبات

### Phase 6 — React Frontend
- **البناء:** `ChatWindow.jsx` (رسائل + input)، `api.js` (استدعاء الـ backend)، تحميل سجل المحادثة القديم عند فتح الصفحة (`GET /api/history/<session_id>` — endpoint إضافي بسيط)
- **الفحص:** اختبار يدوي: إرسال 3-4 رسائل متتالية، إعادة تحميل الصفحة، التأكد أن السجل يظهر
- **التوثيق:** لقطة شاشة (screenshot) للواجهة تُضاف لمجلد `docs/`
- **معيار الإنجاز:** محادثة كاملة تعمل من الواجهة حتى الرد

### Phase 7 — اختبار شامل (End-to-End) وتوثيق نهائي
- **البناء:** لا بناء جديد — مراجعة شاملة فقط
- **الفحص:** سيناريوهات اختبار end-to-end موثقة (10 سيناريوهات تغطي: كل الفئات الأربع، حالة رقم طلب غير موجود، حالة رسالة غامضة، حالة تصعيد لتذكرة)
- **التوثيق:** تحديث `README.md` النهائي + تقرير مشروع نهائي يلخص كل مرحلة ونتائجها
- **معيار الإنجاز:** المشروع جاهز للعرض أمام اللجنة

---

## 11. قواعد التوثيق والتتبع الصارمة (تنطبق على كل المراحل)

1. **كل دالة تحتوي docstring** يشرح: الغرض، المدخلات، المخرجات، حالات الفشل المحتملة
2. **`PROGRESS.md`** يُحدَّث فور انتهاء كل Phase — لا يُؤجَّل التحديث لنهاية المشروع
3. **لا افتراضات صامتة**: أي قرار غير محسوم بهذا الـ ADR (مثلاً اسم المتجر الوهمي، عدد المنتجات بالضبط) يُطرح كسؤال صريح على صاحب المشروع قبل التنفيذ، لا يُخترع من قبل المنفّذ
4. **رسائل الالتزام (commits)** إن استُخدم git: بصيغة `[Phase N] وصف مختصر بالإنجليزي`
5. **أي خطأ أو نتيجة غير متوقعة أثناء التنفيذ يُبلَّغ فوراً**، لا يُخفى أو "يُصلَح بصمت" دون ذكره

---

## 12. أسئلة مفتوحة يجب حسمها قبل Phase 0 (أو تُترك بقيم افتراضية معلنة)

- [ ] اسم المتجر الوهمي وقائمة المنتجات النهائية (10-15 منتج) — افتراضي إن لم يُحدَّد: "متجر النخبة" بمنتجات إلكترونية عامة
- [ ] اللهجة الدقيقة (خليجية بحتة / يمنية بحتة / مزيج) — تم تحديدها سابقاً كـ "عامية واقعية" عامة، يُفضَّل تحديد لهجة واحدة مهيمنة لتقليل تشتت المفردات بالتدريب
- [ ] حجم الداتا سيت النهائي المستهدف (اقتراح: 4000-6000 صف)
