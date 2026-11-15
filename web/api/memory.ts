// GET    /api/memory   -> { enabled, messages, notes }   (header x-finn-user)
// POST   /api/memory   -> append messages {messages:[...]} (used for offline answers)
//                         or run a memory command {command:"remember that …"}
// DELETE /api/memory   -> clear this user's chat history (notes stay unless asked)
import { clearHistory, history, memoryCommand, memoryOn, notes, saveMessages, validUser } from "./_supabase.js";

export default async function handler(req: any, res: any) {
  const user = req.headers["x-finn-user"];
  if (!memoryOn()) return res.status(200).json({ enabled: false, messages: [], notes: [] });
  if (!validUser(user)) return res.status(400).json({ error: "missing user id" });
  try {
    if (req.method === "GET") {
      const [m, n] = await Promise.all([history(user), notes(user)]);
      return res.status(200).json({ enabled: true, messages: m, notes: n.map((x) => x.note) });
    }
    if (req.method === "POST") {
      const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
      if (typeof body.command === "string") {
        const reply = await memoryCommand(user, body.command);
        return res.status(200).json({ handled: reply != null, reply });
      }
      const msgs = (Array.isArray(body.messages) ? body.messages : []).slice(-4)
        .filter((m: any) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string");
      await saveMessages(user, msgs);
      return res.status(200).json({ ok: true });
    }
    if (req.method === "DELETE") {
      await clearHistory(user);
      return res.status(200).json({ ok: true });
    }
    return res.status(405).json({ error: "method not allowed" });
  } catch (e: any) {
    return res.status(502).json({ error: String(e?.message || e).slice(0, 200) });
  }
}
