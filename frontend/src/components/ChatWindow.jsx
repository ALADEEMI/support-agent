import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHistory, sendMessage } from "../api";
import OrderCard from "./OrderCard";
import "./ChatWindow.css";

/** أقل تأخير قبل إظهار مؤشر «سارة تكتب» (إيقاع طبيعي بدل الظهور اللحظي). */
const TYPING_DELAY_MS = 700;

/** أقل مدة يُعرض فيها المؤشر حتى لو ردّ الـ backend بسرعة. */
const TYPING_MIN_VISIBLE_MS = 400;

/** مدة إخفاء المؤشر المتدرّج (مطابقة لمدة الانتقال في CSS). */
const TYPING_FADE_MS = 260;

/** اقتراحات سريعة تُعبّئ حقل الإدخال وتُرسل مباشرة. */
const QUICK_REPLIES = [
  "🚚 وين طلبي رقم 1002؟",
  "🔄 ما هي سياسة الاسترجاع والاستبدال؟",
  "📦 ايش المنتجات المتوفرة عندكم؟",
  "✍️ أشتي أرفع شكوى",
];

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
 * نافذة المحادثة: تعرض رسائل الجلسة النشطة، ترسل رسائل جديدة، وتحمّل السجل عند
 * تبديل الجلسة. الحالة (الجلسة النشطة) تصل من `App` ليتسنّى للشريط الجانبي تبديلها.
 *
 * @param {object} props - الخصائص.
 * @param {string} props.sessionId - معرّف الجلسة النشطة.
 * @param {() => void} [props.onTurnComplete] - يُستدعى بعد انتهاء الدورة (لتحديث الشريط).
 * @returns {JSX.Element} واجهة المحادثة.
 */
export default function ChatWindow({ sessionId, onTurnComplete }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [typingPhase, setTypingPhase] = useState("hidden");
  const listRef = useRef(null);
  const historyRequestRef = useRef(0);

  useEffect(() => {
    const requestId = historyRequestRef.current + 1;
    historyRequestRef.current = requestId;

    setMessages([]);
    setError(null);
    setTypingPhase("hidden");

    fetchHistory(sessionId)
      .then((history) => {
        if (historyRequestRef.current !== requestId) {
          return; // جلسة أخرى صارت نشطة — تجاهل الرد المتأخر.
        }
        // نوحّد شكل رسائل السجل مع شكل رسائل الدورة الحيّة، حتى تُرسم بطاقة
        // الطلب المحفوظة في `metadata` بنفس الطريقة بعد إعادة فتح الجلسة.
        const restored = history.map((message) => ({
          sender: message.sender,
          content: message.content,
          timestamp: message.timestamp,
          orderDetails: message.order_details || null,
        }));
        // لا تستبدل رسائل أضافها المستخدم أثناء تحميل السجل.
        setMessages((previous) => (previous.length === 0 ? restored : previous));
      })
      .catch((err) => {
        if (historyRequestRef.current === requestId) {
          setError(err.message);
        }
      });
  }, [sessionId]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, typingPhase]);

  /**
   * ينفّذ طلب الـ backend مع إدارة إيقاع مؤشر الكتابة (تأخير الظهور + أقل مدة عرض).
   *
   * @param {string} text - نص الرسالة.
   * @returns {Promise<object>} استجابة الـ backend.
   */
  const requestWithTypingCadence = useCallback(async (text) => {
    let shown = false;
    const startedAt = Date.now();
    const showTimer = setTimeout(() => {
      shown = true;
      setTypingPhase("showing");
    }, TYPING_DELAY_MS);

    try {
      return await sendMessage(sessionId, text);
    } finally {
      clearTimeout(showTimer);
      const elapsed = Date.now() - startedAt;

      if (!shown) {
        // الرد وصل قبل التأخير: أظهر المؤشر لمدة رحمة قصيرة ثم أخفِه.
        setTypingPhase("showing");
        await new Promise((resolve) => setTimeout(resolve, TYPING_MIN_VISIBLE_MS));
      } else {
        const visibleFor = elapsed - TYPING_DELAY_MS;
        if (visibleFor < TYPING_MIN_VISIBLE_MS) {
          await new Promise((resolve) => setTimeout(resolve, TYPING_MIN_VISIBLE_MS - visibleFor));
        }
      }

      setTypingPhase("hiding");
      await new Promise((resolve) => setTimeout(resolve, TYPING_FADE_MS));
      setTypingPhase("hidden");
    }
  }, [sessionId]);

  const handleSend = useCallback(
    async (rawText) => {
      const text = (rawText || "").trim();
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
        const data = await requestWithTypingCadence(text);
        setMessages((previous) => [
          ...previous,
          {
            sender: "agent",
            content: data.reply,
            timestamp: localTimestamp(),
            orderDetails: data.order_details || null,
          },
        ]);
      } catch (err) {
        setError(err.message);
      } finally {
        setIsLoading(false);
        if (onTurnComplete) {
          onTurnComplete();
        }
      }
    },
    [isLoading, onTurnComplete, requestWithTypingCadence]
  );

  const handleSubmit = useCallback(
    (event) => {
      event.preventDefault();
      handleSend(input);
    },
    [handleSend, input]
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
                {message.orderDetails && <OrderCard order={message.orderDetails} />}
                {formatTime(message.timestamp) && (
                  <span className="chat-time">{formatTime(message.timestamp)}</span>
                )}
              </div>
            </div>
          ))}

          {typingPhase !== "hidden" && (
            <div className={`chat-row chat-row-agent chat-typing-row is-${typingPhase}`}>
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

        {!isLoading && (
          <div className="chat-chips" aria-label="اقتراحات سريعة">
            {QUICK_REPLIES.map((chip) => (
              <button
                type="button"
                key={chip}
                className="chat-chip"
                onClick={() => handleSend(chip)}
              >
                {chip}
              </button>
            ))}
          </div>
        )}

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
