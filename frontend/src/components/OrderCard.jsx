/** مراحل خط سير الطلب الطبيعية (بترتيب قاعدة البيانات في schema.sql). */
const PIPELINE_STEPS = ["قيد التجهيز", "قيد الشحن", "تم التوصيل"];

/** ألوان وسم الحالة لكل حالة من الحالات الأربع المعتمدة. */
const STATUS_TONE = {
  "قيد التجهيز": "order-pill-processing",
  "قيد الشحن": "order-pill-shipped",
  "تم التوصيل": "order-pill-delivered",
  "ملغي": "order-pill-cancelled",
};

/**
 * بطاقة تفاعلية تعرض تفاصيل الطلب داخل فقاعة الوكيل.
 *
 * الحالات الثلاث الأولى (قيد التجهيز / قيد الشحن / تم التوصيل) تُعرض كخط سير
 * من ثلاث خطوات مع تمييز المرحلة الحالية. الحالة الرابعة (`ملغي`) تُعرض كوسم
 * أحمر مع تنبيه صريح بالإلغاء بدل خط سير نشط (لا معنى لمسار توصيل لطلب ملغي).
 *
 * @param {object} props - الخصائص.
 * @param {object} props.order - تفاصيل الطلب من الـ backend: `order_id`,
 *   `product_name`, `status`, `order_date`, `expected_delivery`.
 * @returns {JSX.Element} بطاقة الطلب.
 */
export default function OrderCard({ order }) {
  const isCancelled = order.status === "ملغي";
  const activeIndex = PIPELINE_STEPS.indexOf(order.status);
  const tone = STATUS_TONE[order.status] || "order-pill-processing";

  return (
    <div className="order-card">
      <div className="order-card-head">
        <span className="order-card-title">تفاصيل الطلب</span>
        <span className={`order-pill ${tone}`}>{order.status}</span>
      </div>

      <dl className="order-card-grid">
        <div className="order-card-field">
          <dt>المنتج</dt>
          <dd>{order.product_name || "—"}</dd>
        </div>
        <div className="order-card-field">
          <dt>رقم الطلب</dt>
          <dd>#{order.order_id}</dd>
        </div>
        <div className="order-card-field">
          <dt>تاريخ الطلب</dt>
          <dd>{order.order_date || "—"}</dd>
        </div>
        <div className="order-card-field">
          <dt>التوصيل المتوقع</dt>
          <dd>{order.expected_delivery || "—"}</dd>
        </div>
      </dl>

      {isCancelled ? (
        <div className="order-cancelled-alert" role="alert">
          <span aria-hidden="true">⚠️</span>
          <span>
            هذا الطلب حالته «ملغي» — تم إلغاء الطلب، فما فيه خط توصيل نشط. لو تحتاج تعرف سبب
            الإلغاء أو تحب نعيد الطلب، خبرني وأنا أتابع معك.
          </span>
        </div>
      ) : (
        <ol className="order-steps" aria-label="مراحل الطلب">
          {PIPELINE_STEPS.map((step, index) => {
            const state = index < activeIndex ? "is-done" : index === activeIndex ? "is-current" : "is-todo";
            return (
              <li key={step} className={`order-step ${state}`}>
                <span className="order-step-dot" aria-hidden="true">
                  {state === "is-done" ? "✓" : ""}
                </span>
                <span className="order-step-label">{step}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
