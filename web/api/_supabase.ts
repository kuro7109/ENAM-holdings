// Minimal Supabase (PostgREST) client for the server functions. No SDK: plain fetch.
// Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Vercel env. Never sent to the browser.

// Accept whatever was pasted (".../rest/v1/", a trailing slash, spaces): keep only the origin.
const URL_ = () => {
  const raw = (process.env.SUPABASE_URL || "").trim();
  try { return new URL(raw).origin; } catch { return raw.replace(/\/+$/, ""); }
};
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

/** Is memory actually usable? Checks both tables with the real key. Never returns the key. */
export async function health(): Promise<{ ok: boolean; error?: string; host?: string; key?: string; hint?: string }> {
  const raw = URL_(), key = KEY();
  let host = "";
  try { host = new URL(raw).host; } catch { /* reported below */ }
  const keyType = !key ? "missing" : key.startsWith("eyJ") ? "legacy JWT" : key.startsWith("sb_secret_") ? "secret (sb_secret_)"
    : key.startsWith("sb_publishable_") ? "publishable (wrong one)" : "unrecognised";
  if (!raw || !key) return { ok: false, error: "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set", host, key: keyType };
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.(co|in)$/i.test(raw))
    return { ok: false, host, key: keyType, error: "SUPABASE_URL should look exactly like https://<project-ref>.supabase.co (no path, no trailing slash)" };
  if (keyType === "publishable (wrong one)")
    return { ok: false, host, key: keyType, error: "This is the publishable key. Use the secret key (sb_secret_…) or the legacy service_role key." };
  try {
    await rest("finn_messages?select=id&limit=1");
    await rest("finn_memories?select=id&limit=1");
    return { ok: true, host, key: keyType };
  } catch (e: any) {
    const msg = String(e?.message || e);
    const hint = /PGRST205|does not exist|schema cache/i.test(msg) ? "Tables missing: run supabase/schema.sql in the Supabase SQL Editor."
      : /401|Invalid API key|JWT/i.test(msg) ? "Key rejected: copy the secret (or service_role) key again."
      : /404/.test(msg) ? "Wrong project URL." : undefined;
    return { ok: false, host, key: keyType, error: msg.slice(0, 200), hint };
  }
}
