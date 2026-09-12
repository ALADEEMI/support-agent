import "./ChatSidebar.css";

/** ترجمة حالة الجلسة القادمة من الـ backend إلى وسم عربي ولون. */
const STATUS_META = {
  escalated: { label: "تذكرة متابعة", className: "session-badge-escalated" },
  resolved: { label: "تم الحل", className: "session-badge-resolved" },
  unresolved: { label: "معلقة", className: "session-badge-unresolved" },
  active: { label: "محادثة عامة", className: "session-badge-active" },
};

/**
 * ينسّق الطابع الزمني القادم من قاعدة البيانات (`YYYY-MM-DD HH:MM:SS`).
 *
 * @param {string} timestamp - الطابع الزمني.
 * @returns {string} صيغة مختصرة `MM/DD HH:MM`، أو نص فارغ إذا تعذّر التحليل.
 */
function formatDateTime(timestamp) {
  if (typeof timestamp !== "string") {
    return "";
  }
  const match = timestamp.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return match ? `${match[2]}/${match[3]} ${match[4]}:${match[5]}` : timestamp;
}

/**
 * شريط جانبي يعرض سجل المحادثات مع حالتها، ويتيح بدء محادثة جديدة أو فتح قديمة.
 *
 * @param {object} props - الخصائص.
 * @param {Array<object>} props.sessions - ملخّص الجلسات من `/api/sessions`.
 * @param {string} props.activeSessionId - معرّف الجلسة النشطة حالياً.
 * @param {(sessionId: string) => void} props.onSelectSession - يُستدعى عند اختيار جلسة.
 * @param {() => void} props.onNewChat - يُستدعى عند طلب محادثة جديدة.
 * @returns {JSX.Element} الشريط الجانبي.
 */
export default function ChatSidebar({ sessions, activeSessionId, onSelectSession, onNewChat }) {
  return (
    <aside className="sidebar" aria-label="سجل المحادثات">
      <div className="sidebar-head">
        <span className="sidebar-logo" aria-hidden="true">
          ن
        </span>
        <h2 className="sidebar-title">محادثاتي</h2>
      </div>

      <button type="button" className="sidebar-new" onClick={onNewChat}>
        + محادثة جديدة
      </button>

      <div className="sidebar-list">
        {sessions.length === 0 && (
          <p className="sidebar-empty">ما فيه محادثات سابقة بعد. ابدأ محادثة جديدة وأنا معك.</p>
        )}

        {sessions.map((session) => {
          const meta = STATUS_META[session.status] || STATUS_META.active;
          const isActive = session.session_id === activeSessionId;
          return (
            <button
              type="button"
              key={session.session_id}
              className={`sidebar-item${isActive ? " is-active" : ""}`}
              onClick={() => onSelectSession(session.session_id)}
              aria-current={isActive ? "true" : undefined}
            >
              <span className="sidebar-item-top">
                <span className="sidebar-item-title">{session.first_message || "محادثة بدون عنوان"}</span>
                <span className={`session-badge ${meta.className}`}>{meta.label}</span>
              </span>
              <span className="sidebar-item-snippet">{session.last_message}</span>
              <span className="sidebar-item-meta">
                <span>{formatDateTime(session.updated_at)}</span>
                <span>{session.message_count} رسالة</span>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
