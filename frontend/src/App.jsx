import { useCallback, useEffect, useState } from "react";

import { fetchSessions } from "./api";
import ChatSidebar from "./components/ChatSidebar";
import ChatWindow from "./components/ChatWindow";
import "./App.css";

const SESSION_KEY = "support-agent-session-id";

/**
 * ينشئ معرّف جلسة فريداً جديداً.
 *
 * @returns {string} معرّف الجلسة.
 */
function createSessionId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * يقرأ معرّف الجلسة النشط من `localStorage`، وينشئ واحداً عند أول زيارة.
 *
 * @returns {string} معرّف الجلسة النشط.
 */
function initialSessionId() {
  const stored = window.localStorage.getItem(SESSION_KEY);
  if (stored) {
    return stored;
  }
  const created = createSessionId();
  window.localStorage.setItem(SESSION_KEY, created);
  return created;
}

/**
 * هيكل التطبيق: يملك الجلسة النشطة وقائمة الجلسات، وينسّق بين الشريط الجانبي
 * ونافذة المحادثة (رفع الحالة إلى الأعلى حتى يستطيع الشريط تبديل الجلسات).
 *
 * @returns {JSX.Element} واجهة التطبيق.
 */
export default function App() {
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [sessions, setSessions] = useState([]);

  const refreshSessions = useCallback(() => {
    fetchSessions()
      .then(setSessions)
      .catch((err) => {
        // لا نُفرغ القائمة عند فشل التحديث — نُبقي آخر قائمة معروفة ونسجّل الخطأ.
        console.error("تعذّر جلب قائمة المحادثات:", err.message);
      });
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const selectSession = useCallback(
    (selectedId) => {
      window.localStorage.setItem(SESSION_KEY, selectedId);
      setSessionId(selectedId);
      refreshSessions();
    },
    [refreshSessions]
  );

  const startNewChat = useCallback(() => {
    const created = createSessionId();
    window.localStorage.setItem(SESSION_KEY, created);
    setSessionId(created);
    refreshSessions();
  }, [refreshSessions]);

  return (
    <div className="app-shell">
      <ChatSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onSelectSession={selectSession}
        onNewChat={startNewChat}
      />
      <ChatWindow sessionId={sessionId} onTurnComplete={refreshSessions} />
    </div>
  );
}
