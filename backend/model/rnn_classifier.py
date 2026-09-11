"""تحميل نموذج RNN والتوكنايزر + دالة `predict()`.

يتوقع الملفات الثلاثة في `backend/model/artifacts/` بالمسارات المحددة في
ADR قسم 6.1 و 3 (`model.h5`، `tokenizer.pkl`، `label_encoder.pkl`).

يُبنى بالكامل في Phase 4، ولا يُستخدم أي ملف وهمي (mock) إذا لم تكن الملفات موجودة.
"""
