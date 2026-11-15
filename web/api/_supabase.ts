// Minimal Supabase (PostgREST) client for the server functions. No SDK: plain fetch.
// Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel env. Never sent to the browser.

const URL_ = () => (process.env.SUPABASE_URL || "").replace(/\/$/, "");
const KEY = () => process.env.SUPABASE_SERVICE_ROLE_KEY || "";
export const memoryOn = () => Boolean(URL_() && KEY());

async function rest(path: string, init: RequestInit = {}): Promise<any> {
  const r = await fetch(`${URL_()}/rest/v1/${path}`, {
    ...init,
    // Legacy service_role keys are JWTs and go in both headers; new sb_secret_ keys go in apikey only.
    headers: { apikey: KEY(), ...(KEY().startsWith("eyJ") ? { Authorization: `Bearer ${KEY()}` } : {}),
      "Content-Type": "application/json", Prefer: "return=minimal", ...(init.headers || {}) },
    signal: AbortSignal.timeout(8000),
  });
  if (!r.ok) throw new Error(`supabase ${r.status}: ${(await r.text()).slice(0, 160)}`);
  return r.status === 204 || init.method === "POST" || init.method === "DELETE" ? null : r.json();
}

export const validUser = (u: unknown): u is string => typeof u === "string" && /^[a-zA-Z0-9-]{16,64}$/.test(u);
const enc = encodeURIComponent;

export async function history(user: string, limit = 30) {
  const rows = await rest(`finn_messages?user_id=eq.${enc(user)}&select=role,content,mode,symbols,created_at&order=created_at.desc&limit=${limit}`);
  return (rows || []).reverse();
}
export async function saveMessages(user: string, msgs: { role: string; content: string; mode?: string; symbols?: string[] }[]) {
  if (!msgs.length) return;
  await rest("finn_messages", { method: "POST", body: JSON.stringify(msgs.map((m) => ({
    user_id: user, role: m.role, content: String(m.content).slice(0, 4000), mode: m.mode || null,
    symbols: (m.symbols || []).slice(0, 8) }))) });
}
export async function notes(user: string): Promise<{ id: number; note: string }[]> {
  return (await rest(`finn_memories?user_id=eq.${enc(user)}&select=id,note&order=created_at.asc&limit=50`)) || [];
}
export async function addNote(user: string, note: string) {
  await rest("finn_memories", { method: "POST", body: JSON.stringify({ user_id: user, note: note.slice(0, 300) }) });
}
export async function forget(user: string, match?: string) {
  if (!match) {
    await rest(`finn_memories?user_id=eq.${enc(user)}`, { method: "DELETE" });
    return;
  }
  const all = await notes(user);
  const hit = all.filter((n) => n.note.toLowerCase().includes(match.toLowerCase()));
  for (const n of hit) await rest(`finn_memories?id=eq.${n.id}&user_id=eq.${enc(user)}`, { method: "DELETE" });
  return hit.length;
}
export async function clearHistory(user: string) {
  await rest(`finn_messages?user_id=eq.${enc(user)}`, { method: "DELETE" });
}

/** "remember that …", "what do you remember", "forget …": handled without a model. */
export async function memoryCommand(user: string, q: string): Promise<string | null> {
  const t = q.trim();
  let m = t.match(/^(?:please\s+)?(?:remember|note|keep in mind)(?:\s+that)?[:,]?\s+(.{3,})$/i);
  if (m) {
    await addNote(user, m[1].replace(/[.!]+$/, ""));
    return `Noted. I'll keep in mind: "${m[1].replace(/[.!]+$/, "")}". Say "what do you remember?" to see everything, or "forget …" to remove it.`;
  }
  if (/^what do you (remember|know about me)|^show (my )?memor/i.test(t)) {
    const n = await notes(user);
    return n.length ? `I remember ${n.length} thing${n.length === 1 ? "" : "s"}:\n${n.map((x) => `• ${x.note}`).join("\n")}`
      : `Nothing yet. Tell me "remember that …" and I'll use it in later answers.`;
  }
  m = t.match(/^forget(?:\s+about)?\s+(.+)$/i);
  if (m) {
    if (/^(everything|all|it all)\b/i.test(m[1])) { await forget(user); return "Done. I've forgotten everything you asked me to remember."; }
    const k = await forget(user, m[1].replace(/[.!]+$/, ""));
    return k ? `Done. Removed ${k} note${k === 1 ? "" : "s"} about "${m[1]}".` : `I don't have a note about "${m[1]}".`;
  }
  return null;
}
