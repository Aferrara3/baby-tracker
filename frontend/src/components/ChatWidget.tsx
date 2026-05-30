import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { clsx } from 'clsx';
import { LoaderCircle, MessageCircleMore, Send, X } from 'lucide-react';

import { API_BASE } from '../config';

const MODEL_UNAVAILABLE_MESSAGE =
  "Model unavailable at this time. This is a homelab hosted app and I use my computer for other things, so I do not always keep the chat model warm. Try again later or text me if you'd like your account linked to your own chat API billing.";
const BROWSER_TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

interface ChatWidgetProps {
  authHeaders: { Authorization: string };
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface ChatReadinessResponse {
  ready: boolean;
  provider: string;
  model: string;
  detail: string | null;
}

interface ChatQueryResponse {
  status: 'answered' | 'rejected' | 'unavailable';
  reply: string;
}

function getApiErrorDetail(error: unknown): string | null {
  return axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string'
    ? error.response.data.detail
    : null;
}

const INITIAL_ASSISTANT_MESSAGE = `Ask about your tracked data.

Examples:
- How many times did my baby poop in the last 7 days?
- How much time was spent nursing so far today?
- How many oz did the baby eat?`;

export default function ChatWidget({ authHeaders }: ChatWidgetProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 'chat-welcome', role: 'assistant', content: INITIAL_ASSISTANT_MESSAGE },
  ]);
  const [draftMessage, setDraftMessage] = useState('');
  const [isCheckingReadiness, setIsCheckingReadiness] = useState(false);
  const [readiness, setReadiness] = useState<'unknown' | 'ready' | 'unavailable'>('unknown');
  const [modelLabel, setModelLabel] = useState('');
  const [isSending, setIsSending] = useState(false);
  const chatSessionIdRef = useRef(
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  );
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const lastAssistantMessage = useMemo(() => messages[messages.length - 1]?.content ?? '', [messages]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || isSending) {
      return;
    }
    if (readiness === 'ready') {
      return;
    }

    let cancelled = false;
    const checkReadiness = async () => {
      setIsCheckingReadiness(true);
      try {
        const response = await axios.get<ChatReadinessResponse>(`${API_BASE}/chat/readiness`, {
          headers: authHeaders,
        });
        if (cancelled) {
          return;
        }
        setModelLabel(`${response.data.provider}:${response.data.model}`);
        if (response.data.ready) {
          setReadiness('ready');
          return;
        }
        setReadiness('unavailable');
        setMessages((current) =>
          current.some((message) => message.content === MODEL_UNAVAILABLE_MESSAGE)
            ? current
            : [...current, { id: `chat-unavailable-${Date.now()}`, role: 'assistant', content: MODEL_UNAVAILABLE_MESSAGE }],
        );
      } catch {
        if (cancelled) {
          return;
        }
        setReadiness('unavailable');
        setMessages((current) =>
          current.some((message) => message.content === MODEL_UNAVAILABLE_MESSAGE)
            ? current
            : [...current, { id: `chat-unavailable-${Date.now()}`, role: 'assistant', content: MODEL_UNAVAILABLE_MESSAGE }],
        );
      } finally {
        if (!cancelled) {
          setIsCheckingReadiness(false);
        }
      }
    };

    void checkReadiness();
    return () => {
      cancelled = true;
    };
  }, [authHeaders, isOpen, isSending, readiness]);

  useEffect(() => {
    if (!isOpen || !scrollContainerRef.current) {
      return;
    }
    scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
  }, [isOpen, isSending, messages]);

  const handleSend = async () => {
    const trimmedMessage = draftMessage.trim();
    if (!trimmedMessage || isSending || isCheckingReadiness) {
      return;
    }

    if (readiness === 'unavailable') {
      setMessages((current) =>
        current.some((message) => message.content === MODEL_UNAVAILABLE_MESSAGE)
          ? current
          : [...current, { id: `chat-unavailable-${Date.now()}`, role: 'assistant', content: MODEL_UNAVAILABLE_MESSAGE }],
      );
      return;
    }

    const nextUserMessage: ChatMessage = {
      id: `chat-user-${Date.now()}`,
      role: 'user',
      content: trimmedMessage,
    };

    const nextMessages = [...messages, nextUserMessage];
    setMessages(nextMessages);
    setDraftMessage('');
    setIsSending(true);

    try {
      const response = await axios.post<ChatQueryResponse>(
        `${API_BASE}/chat/query`,
        {
          messages: nextMessages.map((message) => ({
            role: message.role,
            content: message.content,
          })),
          time_zone: BROWSER_TIME_ZONE,
          chat_session_id: chatSessionIdRef.current,
        },
        { headers: authHeaders },
      );
      if (response.data.status === 'unavailable') {
        setReadiness('unavailable');
      }
      setMessages((current) => [
        ...current,
        {
          id: `chat-assistant-${Date.now()}`,
          role: 'assistant',
          content: response.data.reply,
        },
      ]);
    } catch (error) {
      const errorMessage = getApiErrorDetail(error) ?? 'Chat is unavailable right now.';
      setMessages((current) => [
        ...current,
        {
          id: `chat-error-${Date.now()}`,
          role: 'assistant',
          content: errorMessage,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="app-icon-button fixed bottom-[calc(env(safe-area-inset-bottom)+1rem)] right-4 z-40 inline-flex h-14 w-14 items-center justify-center rounded-full border shadow-lg backdrop-blur-md transition hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--app-bg)]"
        aria-label="Open chat with your data"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        title="Chat with your data"
      >
        <MessageCircleMore size={22} />
        <span className="absolute bottom-0 right-0 translate-x-[18%] translate-y-[18%] rounded-full bg-amber-500 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-[0.18em] text-slate-950 shadow-md">
          Beta
        </span>
      </button>

      <div
        className={clsx(
          'app-overlay fixed inset-0 z-[45] flex items-end justify-end px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-6 transition-all duration-200',
          isOpen ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={() => setIsOpen(false)}
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="chat-widget-title"
          className={clsx(
            'app-surface relative flex h-[min(42rem,calc(100vh-7rem))] w-full max-w-md flex-col overflow-hidden rounded-3xl border shadow-2xl transition-transform duration-200',
            isOpen ? 'translate-y-0' : 'translate-y-8',
          )}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="app-subtle flex items-start justify-between gap-3 border-b px-4 py-4 [border-color:var(--app-border)]">
            <div className="space-y-1">
              <div className="app-accent-soft inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]">
                <MessageCircleMore size={14} />
                Chat with your data
              </div>
              <h2 id="chat-widget-title" className="text-base font-semibold">
                Beta analytics chat
              </h2>
              <p className="app-muted text-xs">
                {isCheckingReadiness
                  ? 'Checking whether the local model is ready...'
                  : readiness === 'ready'
                    ? `Ready${modelLabel ? ` · ${modelLabel}` : ''}`
                    : 'Account-scoped app-data questions only'}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="app-icon-button rounded-full p-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--app-surface)]"
              aria-label="Close chat"
            >
              <X size={16} />
            </button>
          </div>

          <div ref={scrollContainerRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((message) => (
              <div
                key={message.id}
                className={clsx(
                  'max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm whitespace-pre-wrap',
                  message.role === 'user' ? 'ml-auto bg-[var(--app-accent)] text-white' : 'app-subtle',
                )}
              >
                {message.content}
              </div>
            ))}
            {isSending && (
              <div className="app-subtle flex max-w-[88%] items-center gap-2 rounded-2xl px-4 py-3 text-sm shadow-sm">
                <LoaderCircle size={16} className="animate-spin" />
                Thinking...
              </div>
            )}
          </div>

          <div className="border-t px-4 py-4 [border-color:var(--app-border)]">
            <div className="mb-2 app-muted text-xs">
              {lastAssistantMessage === MODEL_UNAVAILABLE_MESSAGE
                ? 'The model is unavailable right now.'
                : 'Only questions about your own tracked app data are allowed.'}
            </div>
            <div className="flex items-end gap-3">
              <textarea
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                placeholder="Ask about this account's data..."
                rows={2}
                disabled={isCheckingReadiness || isSending || readiness === 'unavailable'}
                className="app-input app-focus min-h-[3.5rem] flex-1 resize-none rounded-2xl border px-4 py-3 text-sm outline-none disabled:opacity-60"
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
              />
              <button
                type="button"
                onClick={() => void handleSend()}
                disabled={!draftMessage.trim() || isCheckingReadiness || isSending || readiness === 'unavailable'}
                className="app-primary-button rounded-2xl p-3 transition-all active:scale-95 disabled:opacity-60"
                aria-label="Send chat message"
              >
                {isCheckingReadiness ? <LoaderCircle size={20} className="animate-spin" /> : <Send size={20} strokeWidth={2.5} />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
