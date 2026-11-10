"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useApp } from "@/components/app-shell";
import { api, authCall } from "@/lib/client";
import { fill } from "@/lib/i18n";

type Message = {
  id: number; employee_id: string; sender_id: string; sender_name: string; body: string;
  created_at: string; delivered_at: string | null; read_at: string | null;
};
type Conversation = { employee_id: string; employee_name: string; employee_status: string; unread: number; last_message: Message | null };
type LiveEvent =
  | { type: "message"; message: Message }
  | { type: "read" | "delivered"; employee_id: string; message_ids: number[]; at: string }
  | { type: "typing"; employee_id: string; user_id: string };

const POLL_MS = 5000;

/** The chat's live channel: authenticates with a short-lived token as its first message,
 *  reconnects with growing pauses, and reports whether it is up (the page polls while it is not). */
function useLiveChannel(onEvent: (event: LiveEvent) => void) {
  const [live, setLive] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const handler = useRef(onEvent);
  useEffect(() => { handler.current = onEvent; }, [onEvent]);

  useEffect(() => {
    let stopped = false;
    let failures = 0;
    let timer: number | undefined;
    let ping: number | undefined;

    async function open() {
      const auth = await authCall<{ token: string; url: string }>("socket");
      if (stopped) return;
      if (!auth.ok) return retry();
      const socket = new WebSocket(auth.data.url);
      socketRef.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token: auth.data.token }));
      socket.onmessage = (message) => {
        let event: { type?: string };
        try { event = JSON.parse(String(message.data)); } catch { return; }
        if (event.type === "ready") {
          failures = 0;
          setLive(true);
          ping = window.setInterval(() => socket.readyState === 1 && socket.send('{"type":"ping"}'), 25_000);
        } else if (event.type && !["pong", "expired"].includes(event.type)) handler.current(event as LiveEvent);
      };
      socket.onclose = (closed) => {
        setLive(false);
        window.clearInterval(ping);
        socketRef.current = null;
        if (stopped) return;
        if (closed.code === 4001) timer = window.setTimeout(() => void open(), 0);   // token expired: reconnect now
        else retry();
      };
    }
    function retry() {
      const delay = [2000, 5000, 10000, 30000][Math.min(failures, 3)];
      failures += 1;
      timer = window.setTimeout(() => void open(), delay);
    }
    void open();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.clearInterval(ping);
      socketRef.current?.close();
    };
  }, []);

  const send = useCallback((event: object) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === 1) socket.send(JSON.stringify(event));
  }, []);
  return { live, send };
}

export function MessagesView() {
  const { t, me, lang, refreshBadges } = useApp();
  const m = t.messages;
  const manager = me.user.role === "manager";
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [current, setCurrent] = useState<string | null>(manager ? null : me.user.id);
  const [messages, setMessages] = useState<Message[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [typing, setTyping] = useState("");
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const lastTyping = useRef(0);
  const typingTimer = useRef<number | undefined>(undefined);
  const currentRef = useRef(current);
  useEffect(() => { currentRef.current = current; }, [current]);

  const clock = (iso: string) => new Intl.DateTimeFormat(lang === "ar" ? "ar-u-nu-latn" : "en",
    { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));

  const loadConversations = useCallback(() => {
    if (!manager) return Promise.resolve();
    return api<Conversation[]>("chat/conversations").then((result) => {
      if (!result.ok) return;
      setConversations(result.data);
      setCurrent((c) => c ?? result.data[0]?.employee_id ?? null);
    });
  }, [manager]);

  const markRead = useCallback(async (employeeId: string, rows: Message[]) => {
    if (document.visibilityState !== "visible") return;
    const theirs = rows.filter((r) => r.sender_id !== me.user.id && !r.read_at);
    if (!theirs.length) return;
    const result = await api(`chat/${employeeId}/read`, "POST", { up_to_id: Math.max(...theirs.map((r) => r.id)) });
    if (result.ok) {
      setConversations((list) => list.map((c) => (c.employee_id === employeeId ? { ...c, unread: 0 } : c)));
      refreshBadges();
    }
  }, [me.user.id, refreshBadges]);

  const scrollDown = () => window.setTimeout(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight }), 0);

  const openConversation = useCallback((employeeId: string) =>
    api<{ messages: Message[]; has_more: boolean }>(`chat/${employeeId}/messages`).then((result) => {
      if (employeeId !== currentRef.current) return;      // another conversation was opened meanwhile
      setError(result.ok ? "" : t.app.error);
      if (!result.ok) return;
      setMessages(result.data.messages);
      setHasMore(result.data.has_more);
      scrollDown();
      void markRead(employeeId, result.data.messages);
    }), [markRead, t]);

  useEffect(() => { void loadConversations(); }, [loadConversations]);
  useEffect(() => { if (current) void openConversation(current); }, [current, openConversation]);

  const add = useCallback((message: Message) => {
    if (message.employee_id !== currentRef.current) {
      if (manager) {
        setConversations((list) => {
          const found = list.some((c) => c.employee_id === message.employee_id);
          if (!found) void loadConversations();
          return list.map((c) => (c.employee_id === message.employee_id
            ? { ...c, last_message: message, unread: c.unread + (message.sender_id !== me.user.id ? 1 : 0) } : c));
        });
      }
      refreshBadges();
      return;
    }
    setMessages((list) => (list.some((x) => x.id === message.id) ? list : [...list, message]));
    if (message.sender_id !== me.user.id) {
      setTyping("");
      void markRead(message.employee_id, [message]);
    }
    scrollDown();
  }, [manager, me.user.id, markRead, loadConversations, refreshBadges]);

  const onEvent = useCallback((event: LiveEvent) => {
    if (event.type === "message") add(event.message);
    else if (event.type === "read" || event.type === "delivered") {
      const key = event.type === "read" ? "read_at" : "delivered_at";
      setMessages((list) => list.map((x) => (event.message_ids.includes(x.id) ? { ...x, [key]: event.at } : x)));
    } else if (event.type === "typing" && event.employee_id === currentRef.current) {
      const name = conversations.find((c) => c.employee_id === event.user_id)?.employee_name
        ?? messages.find((x) => x.sender_id === event.user_id)?.sender_name ?? (manager ? "" : m.yourManager);
      setTyping(fill(m.typing, { name: name || "…" }));
      window.clearTimeout(typingTimer.current);
      typingTimer.current = window.setTimeout(() => setTyping(""), 4000);
    }
  }, [add, conversations, messages, manager, m]);

  const { live, send: sendLive } = useLiveChannel(onEvent);

  // polling fallback while the live channel is down
  useEffect(() => {
    if (live) return;
    const timer = window.setInterval(async () => {
      const id = currentRef.current;
      if (!id) return;
      const last = messages.length ? messages[messages.length - 1].id : undefined;
      const result = await api<{ messages: Message[] }>(`chat/${id}/messages${last ? `?after_id=${last}` : ""}`);
      if (result.ok) result.data.messages.forEach(add);
      void loadConversations();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [live, messages, add, loadConversations]);

  async function loadEarlier() {
    if (!current || !messages.length) return;
    const result = await api<{ messages: Message[]; has_more: boolean }>(`chat/${current}/messages?before_id=${messages[0].id}`);
    if (!result.ok) return;
    setMessages((list) => [...result.data.messages, ...list]);
    setHasMore(result.data.has_more);
  }

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    const body = text.trim();
    if (!body || !current) return;
    const result = await api<Message>(`chat/${current}/messages`, "POST", { body });
    if (!result.ok) return setError(result.error === "offline" ? t.auth.errorOffline : result.error);
    setError("");
    setText("");
    add(result.data);
  }

  function onType(value: string) {
    setText(value);
    const now = Date.now();
    if (value && current && now - lastTyping.current > 3000) {
      lastTyping.current = now;
      sendLive({ type: "typing", employee_id: current });
    }
  }

  const state = (x: Message) => (x.read_at ? m.read : x.delivered_at ? m.delivered : m.sent);
  const conv = conversations.find((c) => c.employee_id === current);
  const disabled = manager && conv?.employee_status === "disabled";

  return (
    <div>
      <h1>{m.title}</h1>
      <p className="lead">{manager ? m.leadManager : m.leadEmployee}</p>
      <p className="hint" role="status">{live ? `● ${m.live}` : `○ ${m.reconnecting}`}</p>
      <div className={`card chat${manager ? "" : " single"}`}>
        {manager ? (
          <nav className="conversations" aria-label={m.title}>
            {conversations.length === 0 ? <p className="muted">{m.noEmployees}</p> : conversations.map((c) => (
              <button key={c.employee_id} className="conversation" aria-current={c.employee_id === current ? "true" : undefined}
                      onClick={() => setCurrent(c.employee_id)}>
                <span className="row"><strong>{c.employee_name}</strong><span className="spacer" />
                  {c.unread ? <span className="badge">{fill(m.newCount, { n: c.unread })}</span> : null}</span>
                <span className="preview">{c.last_message ? c.last_message.body : m.noMessages}</span>
              </button>
            ))}
          </nav>
        ) : null}
        <section className="thread" aria-label={manager ? conv?.employee_name ?? m.title : m.yourManager}>
          <h2 style={{ fontSize: "1.1rem" }}>{manager ? conv?.employee_name ?? "" : m.yourManager}</h2>
          <div className="messages" ref={listRef} aria-live="polite" data-testid="messages">
            {hasMore ? <button className="btn btn-small" style={{ alignSelf: "center" }} onClick={() => void loadEarlier()}>{m.earlier}</button> : null}
            {messages.length === 0 ? <p className="muted" style={{ textAlign: "center" }}>{m.empty}</p> : null}
            {messages.map((x) => {
              const mine = x.sender_id === me.user.id;
              return (
                <div key={x.id} className={`bubble${mine ? " mine" : ""}`} data-testid={mine ? "mine" : "theirs"}>
                  {!mine ? <div className="sender">{x.sender_name}</div> : null}
                  <div dir="auto">{x.body}</div>
                  <div className="meta">{clock(x.created_at)}{mine ? ` · ${state(x)}` : ""}</div>
                </div>
              );
            })}
          </div>
          <p className="hint" aria-live="polite">{typing}</p>
          {error ? <p className="error" role="alert">{error}</p> : null}
          {disabled ? <p className="muted">{m.disabledAccount}</p> : (
            <form className="composer" onSubmit={submit}>
              <label className="sr-only" htmlFor="chat-input">{m.placeholder}</label>
              <textarea id="chat-input" value={text} maxLength={4000} placeholder={m.placeholder}
                        onChange={(e) => onType(e.target.value)} disabled={!current}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }} />
              <button className="btn btn-primary" type="submit" disabled={!current || !text.trim()}>{m.send}</button>
            </form>
          )}
        </section>
      </div>
    </div>
  );
}
