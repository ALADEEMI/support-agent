import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHistory, sendMessage } from "../api";
import "./ChatWindow.css";

const SESSION_KEY = "support-agent-session-id";

/**
 * يرجع معرّف جلسة ثابتاً لهذا المتصفح، وينشئه عند أول زيارة إن لم يكن موجوداً.
 *
 * @returns {string} معرّف الجلسة.
 */
function getOrCreateSessionId() {
  let sessionId = window.localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

/**
 * يبني طابعاً زمنياً محلياً بنفس صيغة قاعدة البيانات (`YYYY-MM-DD HH:MM:SS`).
 *
 * @returns {string} الطابع الزمني.
 */
function localTimestamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
  );
}

/**
 * يستخرج الوقت (HH:MM) من طابع زمني بصيغة `YYYY-MM-DD HH:MM:SS`.
 *
 * @param {string} timestamp - الطابع الزمني.
 * @returns {string} الوقت المختصر، أو نص فارغ إذا تعذّر التحليل.
 */
function formatTime(timestamp) {
  if (typeof timestamp !== "string") {
    return "";
  }
  const match = timestamp.match(/(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : "";
}

/**
 * أيقونة عميل عامة (SVG مضمّن — بلا أي مكتبة خارجية).
 *
 * @returns {JSX.Element} الأيقونة.
 */
function CustomerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="8" r="3.6" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M4.8 19.2c0-3.3 3.2-5.4 7.2-5.4s7.2 2.1 7.2 5.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * نافذة المحادثة: تعرض الرسائل، ترسل رسائل جديدة، وتحمّل السجل القديم عند الفتح.
 *
 * @returns {JSX.Element} واجهة المحادثة.
 */
export default function ChatWindow() {
  const [sessionId] = useState(getOrCreateSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const listRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    fetchHistory(sessionId)
      .then((history) => {
        if (cancelled) {
          return;
        }
        // لا تستبدل رسائل أضافها المستخدم أثناء تحميل السجل (سباق زمني حقيقي:
        // لو تأخّر طلب السجل حتى بعد إرسال أول رسالة، كانت النتيجة الفارغة تمحوها).
        setMessages((previous) => (previous.length === 0 ? history : previous));
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      const text = input.trim();
      if (!text || isLoading) {
        return;
      }

      setError(null);
      setIsLoading(true);
      setInput("");
      setMessages((previous) => [
        ...previous,
        { sender: "customer", content: text, timestamp: localTimestamp() },
      ]);

      try {
        const data = await sendMessage(sessionId, text);
        setMessages((previous) => [
          ...previous,
          { sender: "agent", content: data.reply, timestamp: localTimestamp() },
        ]);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    },
    [input, isLoading, sessionId]
  );

  return (
    <div className="chat-page">
      <div className="chat-window">
        <header className="chat-header">
          <span className="chat-logo" aria-hidden="true">
            ن
          </span>
          <div className="chat-brand-text">
            <h1>متجر النخبة</h1>
            <span className="chat-subtitle">خدمة العملاء</span>
          </div>
          <span className="chat-status">
            <span className="chat-status-dot" aria-hidden="true" />
            سارة متصلة
          </span>
        </header>

        <div className="chat-messages" ref={listRef}>
          {messages.length === 0 && !isLoading && (
            <p className="chat-empty">أهلاً بك في متجر النخبة، كيف نقدر نخدمك؟</p>
          )}

          {messages.map((message, index) => (
            <div key={index} className={`chat-row chat-row-${message.sender}`}>
              <span className={`chat-avatar chat-avatar-${message.sender}`} aria-hidden="true">
                {message.sender === "customer" ? <CustomerIcon /> : "ن"}
              </span>
              <div className="chat-bubble-wrap">
                <div className={`chat-bubble chat-bubble-${message.sender}`}>{message.content}</div>
                {formatTime(message.timestamp) && (
                  <span className="chat-time">{formatTime(message.timestamp)}</span>
                )}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="chat-row chat-row-agent">
              <span className="chat-avatar chat-avatar-agent" aria-hidden="true">
                ن
              </span>
              <div className="chat-typing">
                سارة تكتب
                <span className="chat-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            </div>
          )}
        </div>

        {error && <div className="chat-error">تعذّر إتمام الطلب: {error}</div>}

        <form className="chat-form" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="اكتب رسالتك هنا..."
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !input.trim()}>
            إرسال
          </button>
        </form>
      </div>
    </div>
  );
}
