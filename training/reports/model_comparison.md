# مقارنة نماذج RNN — Phase 2

المصدر: `training/reports/model_comparison.csv` (ناتج تشغيل `training_notebook.ipynb` على Google Colab).
مجموعة الاختبار: تقسيم طبقي 70/15/15 (Train/Val/Test) من 4000 صف، `random_state=42`.

## النتائج الفعلية (Test Set)

| النموذج | Test Accuracy | Macro F1 |
|---|---|---|
| **BiLSTM_Baseline** | **0.9450** | **0.9449** |
| BiGRU | 0.9433 | 0.9432 |
| Stacked_BiLSTM | 0.9183 | 0.9185 |

## معماريات النماذج

| النموذج | البنية |
|---|---|
| BiLSTM_Baseline | Embedding(128) → BiLSTM(64) → Dropout(0.4) → Dense(64, relu) → Dropout(0.3) → Dense(4, softmax) |
| Stacked_BiLSTM | Embedding(128) → BiLSTM(64, return_sequences) → Dropout(0.4) → BiLSTM(32) → Dropout(0.3) → Dense(64, relu) → Dense(4, softmax) |
| BiGRU | Embedding(128) → BiGRU(64) → Dropout(0.4) → Dense(64, relu) → Dropout(0.3) → Dense(4, softmax) |

إعدادات التدريب المشتركة: `MAX_VOCAB=15000`، `MAX_LEN=40`، حجم المفردات الفعلي 8056،
`batch_size=32`، `epochs=60` مع EarlyStopping (patience=8) و ReduceLROnPlateau و class_weight متوازن.

## معايير الاختيار

1. **الأعلى في Macro F1** — لأن التوزيع متوازن تماماً (25% لكل فئة)، فـ Macro F1 هو المقياس الأعدل.
2. **البساطة وسرعة الاستدلال** — عند تقارب الأداء يُفضَّل النموذج الأخف لأن الاستدلال يحدث داخل طلب HTTP متزامن.

## القرار

**النموذج المعتمد: `BiLSTM_Baseline`.**

المبرر: يحقق أعلى دقة وأعلى Macro F1 بين النماذج الثلاثة، وهو أبسط بنية (طبقة BiLSTM واحدة)
وبالتالي الأخف استدلالاً داخل الـ backend. الفرق عن `BiGRU` ضئيل (0.0017 في Macro F1) لكنه لصالح
`BiLSTM_Baseline` في المقياسين معاً، ولا مبرر لاختيار نموذج أعقد (`Stacked_BiLSTM`) أداؤه أقل بوضوح.

## مصفوفات الالتباس

- `training/reports/confusion_matrix_BiLSTM_Baseline.png`
- `training/reports/confusion_matrix_BiGRU.png`
- `training/reports/confusion_matrix_Stacked_BiLSTM.png`

منحنيات التدريب: `training/reports/training_curves.png`.

## الملفات الناتجة (المسار المعتمد)

| الملف | المسار |
|---|---|
| `model.keras` | `backend/model/artifacts/model.keras` (مستثنى من git) |
| `tokenizer.pkl` | `backend/model/artifacts/tokenizer.pkl` |
| `label_encoder.pkl` | `backend/model/artifacts/label_encoder.pkl` |
| `config.json` | `backend/model/artifacts/config.json` (`max_len=40`, `vocab_size=8056`) |

## التحقق الفعلي (Sanity Check — ADR 6.1 نقطة 5)

نُفِّذ عبر `backend/tests/test_model_loading.py` على البيئة المحلية (Python 3.12، TensorFlow 2.21 / Keras 3):

```
tests/test_model_loading.py::test_model_files_exist PASSED
tests/test_model_loading.py::test_model_loads PASSED
tests/test_model_loading.py::test_sanity_predictions_are_sensible PASSED
  الرسالة: وينه طلبي يا اخي تاخر كثير مب طبيعي
    → المتوقع: order_inquiry | الفعلي: order_inquiry (ثقة: 0.95)
  الرسالة: ابغى استرجع المنتج لان مو مطابق للمواصفات
    → المتوقع: return_request | الفعلي: return_request (ثقة: 0.64)
  الرسالة: هلا، عندكم توصيل لمنطقة الرياض؟
    → المتوقع: other | الفعلي: other (ثقة: 0.87)
tests/test_model_loading.py::test_normalizer_matches_notebook_training_logic PASSED
tests/test_model_loading.py::test_sanity_predictions_all_classes_supported PASSED
```

## ملاحظة مخاطر (مُبلَّغة ولا تُخفى)

عند تحميل `label_encoder.pkl` تظهر:
`InconsistentVersionWarning: Trying to unpickle estimator LabelEncoder from version 1.6.1 when using version 1.9.1`
أي أن بيئة Colab استخدمت scikit-learn 1.6.1 بينما المحلية 1.9.1. الاختبارات نجحت ولم يظهر أثر سلوكي،
لكن هذا عدم تطابق إصدارات يجب أخذه بالحسبان عند أي إعادة إنتاج مستقبلية.
