// استدعاء الواجهة الخلفية: إرسال رسالة وجلب سجل المحادثة.
// Phase 6 — راجع docs/ADR.md قسم 10.

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:5000";

/**
 * يرسل رسالة العميل إلى الوكيل ويعيد رد الـ backend.
 *
 * @param {string} sessionId - معرّف الجلسة.
 * @param {string} message - نص رسالة العميل.
 * @returns {Promise<object>} كائن الاستجابة: `session_id`, `reply`, `category`,
 *   `order_id`, `product_name`, `needs_escalation`, و`order_details` (تفاصيل الطلب
 *   أو `null`) المستخدمة في بطاقة الطلب.
 * @throws {Error} إذا فشل الطلب أو أعاد الـ backend رمز خطأ.
 */
export async function sendMessage(sessionId, message) {
  const response = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `فشل الطلب (${response.status})`);
  }
  return data;
}

/**
 * يجلب سجل المحادثة الدائم لجلسة معيّنة.
 *
 * @param {string} sessionId - معرّف الجلسة.
 * @returns {Promise<Array<object>>} قائمة رسائل: { message_id, sender, content, timestamp }.
 * @throws {Error} إذا فشل الطلب أو أعاد الـ backend رمز خطأ.
 */
export async function fetchHistory(sessionId) {
  const response = await fetch(`${API_URL}/api/history/${encodeURIComponent(sessionId)}`);

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `فشل جلب السجل (${response.status})`);
  }
  return data.messages || [];
}

/**
 * يجلب ملخّص كل جلسات المحادثة مع حالتها (لسجل المحادثات في الشريط الجانبي).
 *
 * @returns {Promise<Array<object>>} قائمة جلسات: `session_id`, `first_message`,
 *   `last_message`, `updated_at`, `message_count`, `ticket_id`, `status`.
 *   قيم `status`: `escalated` / `resolved` / `unresolved` / `active`.
 * @throws {Error} إذا فشل الطلب أو أعاد الـ backend رمز خطأ.
 */
export async function fetchSessions() {
  const response = await fetch(`${API_URL}/api/sessions`);

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `فشل جلب المحادثات (${response.status})`);
  }
  return data.sessions || [];
}

export { API_URL };
