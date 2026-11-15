/* Ask FINN as its own screen. Talks to /api/chat (model + Supabase memory) and falls back to
   answering from saved data when no model is connected, so it always works. */
import { useEffect, useRef, useState } from "react";
import type { Msg } from "../chat";
import { buildContext, localMemoryCommand, localNotes, mentioned, offlineAnswer, suggestions } from "../chat";
import type { Data, Thresholds } from "../lib";
import { store } from "../lib";
import { buzz } from "../press";

function userId(): string {
  let id = store.get<string | null>("uid", null);
  if (!id) {
    id = (crypto as any).randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
    store.set("uid", id);
  }
  return id!;
}
const H = () => ({ "Content-Type": "application/json", "x-finn-user": userId() });

type Status = { ai: boolean; memory: boolean };
let status: Status | null = null;
async function getStatus(): Promise<Status> {
  if (status) return status;
  try {
    const r = await fetch("/api/chat", { cache: "no-store" });
    const ok = r.ok && (r.headers.get("content-type") || "").includes("json");
    const j = ok ? await r.json() : {};
    status = { ai: Boolean(j.ai), memory: Boolean(j.memory) };
  } catch {
    status = { ai: false, memory: false };
  }
  return status;
}

const STARTERS = [
  "What needs my attention today?", "Did Kaynes keep its promises?", "Any management changes this month?",
  "Compare Havells and Astral", "Which holdings fell the most?", "Any red flags?", "Remember that I care most about margins",
];

export function ChatPage({ data, t, focus, onOpen }: {
  data: Data; t: Thresholds; focus: string | null; onOpen: (symbol: string) => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(() => store.get<Msg[]>("chat", []));
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [st, setSt] = useState<Status | null>(status);
  const [notes, setNotes] = useState<string[]>([]);
  const end = useRef<HTMLDivElement>(null);

  const refreshNotes = (memory: boolean) => {
    if (!memory) { setNotes(localNotes.all()); return; }
    fetch("/api/memory", { headers: H() }).then((x) => x.json()).then((x) => setNotes(x.notes || [])).catch(() => {});
  };

  useEffect(() => {
    (async () => {
      const s = await getStatus();
      setSt(s);
      if (s.memory) {
        try {
          const r = await fetch("/api/memory", { headers: H() });
          const j = await r.json();
          if (j.enabled) {
            if (j.messages?.length) setMsgs(j.messages.map((m: any) => ({ role: m.role, content: m.content, mode: m.mode === "ai" ? "ai" : "offline", symbols: m.symbols || [] })));
            setNotes(j.notes || []);
          }
        } catch { /* keep the history on this device */ }
      } else setNotes(localNotes.all());
    })();
  }, []);
  useEffect(() => { store.set("chat", msgs.slice(-30)); end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);

  const ask = async (text: string) => {
    const question = text.trim().slice(0, 500);
    if (!question || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next);
    setQ("");
    setBusy(true);
    buzz(8);
    const s = await getStatus();
    let reply: Msg | null = null;

    if (s.ai || s.memory) {
      try {
        const ctx = await buildContext(data, question, t, focus);
        const r = await fetch("/api/chat", {
          method: "POST", headers: H(),
          body: JSON.stringify({ context: ctx.text, symbols: ctx.symbols, messages: next.slice(-12).map(({ role, content }) => ({ role, content })) }),
        });
        if (r.ok) {
          const j = await r.json();
          const isMem = j.model === "memory";
          // Buttons for every company the answer names, not just the ones in the question.
          const named = isMem ? [] : [...new Set([...mentioned(data, j.reply), ...ctx.symbols])];
          reply = { role: "assistant", content: j.reply, mode: isMem ? "offline" : "ai", symbols: named };
          if (isMem) refreshNotes(true);
        }
      } catch { /* fall back below */ }
    }
    if (!reply) {
      const mem = s.memory ? null : localMemoryCommand(question);
      if (mem) {
        reply = { role: "assistant", content: mem, mode: "offline", symbols: [] };
        refreshNotes(false);
      } else {
        const o = await offlineAnswer(data, question, t, focus);
        reply = { role: "assistant", content: o.text, mode: "offline", symbols: o.symbols };
      }
      if (s.memory) fetch("/api/memory", { method: "POST", headers: H(), body: JSON.stringify({ messages: [next[next.length - 1], reply] }) }).catch(() => {});
    }
    setMsgs((m) => [...m, reply!]);
    setBusy(false);
    buzz(12);
  };

  const clear = () => {
    setMsgs([]);
    if (st?.memory) fetch("/api/memory", { method: "DELETE", headers: H() }).catch(() => {});
  };

  return (
    <div className="screen chat-page">
      <header className="chat-top">
        <div>
          <h1 className="chat-title">Ask FINN</h1>
        </div>
        {msgs.length > 0 && <button className="linkbtn" onClick={clear}>Clear chat</button>}
      </header>
      <p className="faint tiny" style={{ margin: "6px 0 10px" }}>
        Answers only from FINN's data: filings, prices, your alerts and company research.{focus ? ` Asking about ${focus}.` : ""}
        {" "}Say "remember that …" and it will use it later.
      </p>

      {notes.length > 0 && (
        <details className="notes">
          <summary>{notes.length} thing{notes.length === 1 ? "" : "s"} FINN remembers</summary>
          <ul>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </details>
      )}

      <div className="msgs" aria-live="polite">
        {msgs.length === 0 && <p className="small muted">Ask for exactly what you want instead of hunting for it. Try one of these:</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.content}</div>
            {m.role === "assistant" && (
              <div className="msg-meta">
                {[...new Set(m.symbols || [])].slice(0, 3).map((s) => <button key={s} className="chip sm" onClick={() => onOpen(s)}>Open {s}</button>)}
                <span className="faint tiny">{m.mode === "ai" ? "AI · from FINN's data" : "From saved data"}</span>
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing"><span /><span /><span /></div></div>}
        <div ref={end} />
      </div>

      <div className="chat-dock">
        <div className={`cats chat-sugg ${msgs.length ? "" : "wrap"}`}>
          {(msgs.length ? suggestions(focus, "chat", Object.keys(data.researchIndex)) : STARTERS)
            .map((s) => <button key={s} className="chip sm" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about a holding, a filing, a promise…"
            aria-label="Your question" maxLength={500} enterKeyHint="send" />
          <button className="btn" type="submit" disabled={busy || !q.trim()}>Ask</button>
        </form>
      </div>
    </div>
  );
}
