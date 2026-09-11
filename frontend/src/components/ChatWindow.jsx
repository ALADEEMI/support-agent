import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHistory, sendMessage } from "../api";

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
  }, [messages]);

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
      setMessages((previous) => [...previous, { sender: "customer", content: text }]);

      try {
        const data = await sendMessage(sessionId, text);
        setMessages((previous) => [...previous, { sender: "agent", content: data.reply }]);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    },
    [input, isLoading, sessionId]
  );

  return (
    <div className="chat-window">
      <header className="chat-header">
        <h1>متجر النخبة — خدمة العملاء</h1>
      </header>

      <div className="chat-messages" ref={listRef}>
        {messages.length === 0 && !isLoading && (
          <p className="chat-empty">أهلاً بك، كيف نقدر نخدمك؟</p>
        )}
        {messages.map((message, index) => (
          <div key={index} className={`chat-bubble chat-bubble-${message.sender}`}>
            {message.content}
          </div>
        ))}
        {isLoading && <div className="chat-bubble chat-bubble-agent">جاري الكتابة...</div>}
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
  );
}
