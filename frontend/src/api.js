// استدعاء الواجهة الخلفية `/api/chat` وسجل المحادثة.
// يُبنى بالكامل في Phase 6 (انظر docs/ADR.md قسم 10).

const API_URL = process.env.REACT_APP_API_URL;

export async function sendMessage(sessionId, message) {
  throw new Error("Not implemented until Phase 6");
}

export { API_URL };
