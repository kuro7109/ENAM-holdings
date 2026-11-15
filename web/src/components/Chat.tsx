import { useEffect, useRef, useState } from "react";
import type { Msg } from "../chat";
import { buildContext, offlineAnswer, suggestions } from "../chat";
import type { Data, Thresholds } from "../lib";
import { store } from "../lib";
import { buzz } from "../press";

let aiStatus: boolean | null = null;
async function checkAI(): Promise<boolean> {
  if (aiStatus != null) return aiStatus;
  try {
    const r = await fetch("/api/chat", { cache: "no-store" });
    aiStatus = r.ok && (r.headers.get("content-type") || "").includes("json") && Boolean((await r.json()).ai);
  } catch {
    aiStatus = false;
  }
  return aiStatus;
}

export function Chat({ data, t, tab, focus, onOpen, onClose }: {
  data: Data; t: Thresholds; tab: string; focus: string | null;
  onOpen: (symbol: string) => void; onClose: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(() => store.get<Msg[]>("chat", []));
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ai, setAi] = useState<boolean | null>(aiStatus);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { checkAI().then(setAi); input.current?.focus(); }, []);
  useEffect(() => { store.set("chat", msgs.slice(-20)); end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = prev; window.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const ask = async (text: string) => {
    const question = text.trim().slice(0, 500);
    if (!question || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next);
    setQ("");
    setBusy(true);
    buzz(8);
    let reply: Msg | null = null;
    if (await checkAI()) {
      try {
        const ctx = await buildContext(data, question, t, focus);
        const r = await fetch("/api/chat", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ context: ctx.text, messages: next.slice(-12).map(({ role, content }) => ({ role, content })) }),
        });
        if (r.ok) {
          const j = await r.json();
          reply = { role: "assistant", content: j.reply, mode: "ai", symbols: ctx.symbols };
        }
      } catch { /* fall through to offline */ }
    }
    if (!reply) {
      const o = await offlineAnswer(data, question, t, focus);
      reply = { role: "assistant", content: o.text, mode: "offline", symbols: o.symbols };
      if (ai) setAi(false);
    }
    setMsgs((m) => [...m, reply!]);
    setBusy(false);
    buzz(12);
  };

  return (
    <div className="sheet-back" onClick={onClose} role="dialog" aria-modal="true" aria-label="Ask FINN">
      <div className="sheet chat" onClick={(e) => e.stopPropagation()}>
        <div className="grabber" />
        <div className="chat-head">
          <div>
            <span className="sym" style={{ fontSize: 18 }}>Ask FINN</span>
            <span className={`ai-badge ${ai ? "on" : ""}`} title={ai ? "Answers written by a model, using only FINN's data" : "No model connected: answers come straight from saved data"}>
              {ai == null ? "…" : ai ? "AI" : "Offline"}
            </span>
          </div>
          <div>
            {msgs.length > 0 && <button className="linkbtn" onClick={() => setMsgs([])}>Clear</button>}{" "}
            <button className="linkbtn" onClick={onClose}>Close</button>
          </div>
        </div>
        <p className="faint tiny" style={{ margin: "2px 0 8px" }}>
          Answers only from FINN's own data: filings, prices, your alerts and company research.
          {focus ? ` Looking at ${focus}.` : ""}
        </p>

        <div className="msgs" aria-live="polite">
          {msgs.length === 0 && <p className="muted small">Ask about today's filings, a holding, your alerts, or how well a management team keeps its promises.</p>}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="bubble">{m.content}</div>
              {m.role === "assistant" && (
                <div className="msg-meta">
                  {(m.symbols || []).slice(0, 3).map((s) => (
                    <button key={s} className="chip sm" onClick={() => { onOpen(s); onClose(); }}>Open {s}</button>
                  ))}
                  <span className="faint tiny">{m.mode === "ai" ? "AI · from FINN's data" : "Offline · from saved data"}</span>
                </div>
              )}
            </div>
          ))}
          {busy && <div className="msg assistant"><div className="bubble typing"><span /><span /><span /></div></div>}
          <div ref={end} />
        </div>

        <div className="cats chat-sugg">
          {suggestions(focus, tab, Object.keys(data.researchIndex)).map((s) => <button key={s} className="chip sm" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about a holding, a filing, a promise…"
            aria-label="Your question" maxLength={500} enterKeyHint="send" />
          <button className="btn" type="submit" disabled={busy || !q.trim()}>Ask</button>
        </form>
      </div>
    </div>
  );
}
