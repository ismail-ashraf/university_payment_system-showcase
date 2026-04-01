"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type ChatRole = "user" | "assistant" | "system";

type ChatMessage = {
  role: ChatRole;
  content: string;
  ts: string;
  meta?: {
    intent?: string;
    kind?: "starter" | "fallback";
  };
};

const STORAGE_KEYS = {
  teaserSeen: "student_ai_teaser_seen",
  chatOpened: "student_ai_chat_opened",
  chatHistory: "student_ai_chat_history",
};

const TEASER_COPY = "Need help with your payment? Let's chat";
const CHAT_TITLE = "Payment Assistant";
const CHAT_LABEL = "Inquiry only";
const STARTER_COPY = "أهلًا بك. اختر سؤالًا سريعًا أو اكتب سؤالك هنا.";
const REROUTE_COPY =
  "أقدر أساعدك في وضع الدفع والرسوم والعمليات. اختر سؤالًا سريعًا أو اكتب سؤالك هنا.";
const QUICK_ACTIONS = [
  "العملية الحالية",
  "هل عندي عملية دفع مفتوحة؟",
  "أعمل إيه دلوقتي؟",
  "تاريخ العمليات",
  "الرسوم",
];
const FOLLOW_UP_ACTIONS: Record<string, string[]> = {
  status: ["أعمل إيه دلوقتي؟", "تاريخ العمليات", "الرسوم"],
  transactions: ["العملية الحالية", "أعمل إيه دلوقتي؟"],
  fees: ["العملية الحالية", "تاريخ العمليات"],
};
const MAX_CONTEXT_MESSAGES = 15;

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function getCookie(name: string) {
  if (typeof document === "undefined") return "";
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

function loadHistory(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(STORAGE_KEYS.chatHistory);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && typeof item === "object");
  } catch {
    return [];
  }
}

function saveHistory(messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(STORAGE_KEYS.chatHistory, JSON.stringify(messages));
}

function getSessionFlag(key: string) {
  if (typeof window === "undefined") return "";
  return sessionStorage.getItem(key) || "";
}

function setSessionFlag(key: string) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(key, "1");
}

function buildContext(messages: ChatMessage[]) {
  return messages
    .filter(
      (m) =>
        (m.role === "user" || m.role === "assistant") &&
        m.meta?.kind !== "starter",
    )
    .slice(-MAX_CONTEXT_MESSAGES)
    .map((m) => ({ role: m.role, content: m.content }));
}

export function StudentChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [teaserVisible, setTeaserVisible] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMessages(loadHistory());
    const teaserSeen = getSessionFlag(STORAGE_KEYS.teaserSeen);
    const chatOpened = getSessionFlag(STORAGE_KEYS.chatOpened);
    if (!teaserSeen && !chatOpened) {
      setTeaserVisible(true);
    }
  }, []);

  useEffect(() => {
    saveHistory(messages);
  }, [messages]);

  useEffect(() => {
    if (!teaserVisible) return;
    const timer = window.setTimeout(() => {
      setTeaserVisible(false);
      setSessionFlag(STORAGE_KEYS.teaserSeen);
    }, 7000);
    return () => window.clearTimeout(timer);
  }, [teaserVisible]);

  useEffect(() => {
    if (!isOpen) return;
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [isOpen, messages]);

  useEffect(() => {
    if (!isOpen) return;
    if (messages.length > 0) return;
    setMessages([
      {
        role: "assistant",
        content: STARTER_COPY,
        ts: new Date().toISOString(),
        meta: { kind: "starter" },
      },
    ]);
  }, [isOpen, messages.length]);

  const openChat = () => {
    setIsOpen(true);
    setTeaserVisible(false);
    setSessionFlag(STORAGE_KEYS.chatOpened);
  };

  const closeChat = () => {
    setIsOpen(false);
  };

  const dismissTeaser = () => {
    setTeaserVisible(false);
    setSessionFlag(STORAGE_KEYS.teaserSeen);
  };

  const submitMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const context = buildContext(messages);
    const userMessage: ChatMessage = {
      role: "user",
      content: trimmed,
      ts: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    try {
      const csrfToken = getCookie("csrftoken");
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (csrfToken) headers["X-CSRFToken"] = csrfToken;

      const res = await fetch(`${baseUrl}/api/ai-agent/chat/`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({
          message: trimmed,
          messages: context.length ? context : undefined,
        }),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json || json.success === false) {
        const errorText =
          (json && json.error) || "Something went wrong. Please try again.";
        setMessages((prev) => [
          ...prev,
          { role: "system", content: errorText, ts: new Date().toISOString() },
        ]);
        return;
      }
      const intent = typeof json.intent === "string" ? json.intent : "";
      const isFallback = intent && intent === "out_of_scope";
      const meta = isFallback
        ? { intent, kind: "fallback" as const }
        : intent
          ? { intent }
          : undefined;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: isFallback ? REROUTE_COPY : json.response,
          ts: new Date().toISOString(),
          meta,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          content: "Network error. Please try again.",
          ts: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const sendMessage = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    await submitMessage(text);
  };

  const getMessageChips = (msg: ChatMessage) => {
    if (msg.meta?.kind === "starter") return QUICK_ACTIONS;
    if (msg.role === "assistant" && msg.meta?.intent === "out_of_scope") {
      return QUICK_ACTIONS;
    }
    if (msg.role === "assistant" && msg.meta?.intent) {
      return FOLLOW_UP_ACTIONS[msg.meta.intent] || [];
    }
    return [];
  };

  const launcherLabel = useMemo(() => (isOpen ? "Close" : "Chat"), [isOpen]);

  return (
    <div className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-50 flex flex-col items-end gap-3">
      {teaserVisible && !isOpen ? (
        <div className="max-w-xs rounded-full bg-white border border-slate-200 shadow-sm px-4 py-2 text-sm text-slate-700 flex items-center gap-3">
          <span>{TEASER_COPY}</span>
          <button
            className="text-slate-400 hover:text-slate-600"
            onClick={dismissTeaser}
            aria-label="Dismiss"
          >
            Ã—
          </button>
        </div>
      ) : null}

      {isOpen ? (
        <div className="w-[calc(100vw-32px)] sm:w-[380px] bg-white border border-slate-200 shadow-lg rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <div>
              <div className="text-sm font-semibold">{CHAT_TITLE}</div>
              <div className="text-xs text-slate-500">{CHAT_LABEL}</div>
            </div>
            <button
              className="text-slate-400 hover:text-slate-600"
              onClick={closeChat}
              aria-label="Close chat"
            >
              Ã—
            </button>
          </div>
          <div
            ref={scrollRef}
            className="max-h-[65vh] sm:max-h-[65vh] max-h-[70vh] overflow-y-auto px-4 py-3 space-y-3 bg-slate-50"
          >
            {messages.length === 0 ? (
              <div className="text-sm text-slate-500">{STARTER_COPY}</div>
            ) : null}
            {messages.map((msg, idx) => {
              const chips = getMessageChips(msg);
              return (
                <div
                  key={`${msg.ts}-${idx}`}
                  className={`text-sm ${
                    msg.role === "user"
                      ? "text-right"
                      : msg.role === "assistant"
                        ? "text-left"
                        : "text-left text-slate-500"
                  }`}
                >
                  <span
                    className={`inline-block rounded-2xl px-3 py-2 ${
                      msg.role === "user"
                        ? "bg-slate-900 text-white"
                        : msg.role === "assistant"
                          ? "bg-white border border-slate-200"
                          : "bg-transparent"
                    }`}
                  >
                    {msg.content}
                  </span>
                  {chips.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {chips.map((label) => (
                        <button
                          key={`${msg.ts}-${label}`}
                          type="button"
                          className="text-xs px-3 py-1 rounded-full border border-slate-200 bg-white text-slate-700 hover:bg-slate-100 disabled:opacity-60"
                          onClick={() => submitMessage(label)}
                          disabled={loading}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          <form
            onSubmit={sendMessage}
            className="flex items-center gap-2 px-3 py-3 border-t border-slate-100 bg-white"
          >
            <input
              className="flex-1 border border-slate-300 rounded-full px-3 py-2 text-sm"
              placeholder="Type your question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
            />
            <button
              type="submit"
              className="bg-slate-900 text-white text-sm rounded-full px-4 py-2 disabled:opacity-60"
              disabled={loading}
            >
              {loading ? "..." : "Send"}
            </button>
          </form>
        </div>
      ) : null}

      <button
        className="h-12 w-12 rounded-full bg-slate-900 text-white shadow-lg flex items-center justify-center"
        onClick={isOpen ? closeChat : openChat}
        aria-label="Open chat"
      >
        {launcherLabel}
      </button>
    </div>
  );
}
