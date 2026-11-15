// Vercel serverless function: POST /api/chat  ·  GET /api/chat -> { ai: boolean }
// The key stays here (Vercel env GEMINI_API_KEY, optional GROQ_API_KEY). The client sends only
// the conversation and a compact context it built from FINN's own data; the model answers from
// that context alone. Cheap, fast models first, each with its own free quota.

const SYSTEM = `You are FINN, an analyst assistant inside a portfolio app for Indian listed equities.
Answer ONLY from the CONTEXT below: exchange filings, prices, the user's alerts, and research built
from company filings and earnings-call transcripts. Never use outside knowledge or news.
- Lead with the answer in the first sentence. At most 90 words. Plain text, no markdown headings.
- Use numbers with units (₹ cr, %, ×) and name the company and source (e.g. "Q3 FY26 call", "13 Nov filing").
- If the context doesn't contain the answer, say so in one sentence and name the screen that might help
  (Brief, Alerts, Holdings, Research).
- Do not recommend buying or selling. Describe what the data shows.`;

type M = { role: "user" | "assistant"; content: string };

const GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions";
const GROQ = "https://api.groq.com/openai/v1/chat/completions";

function chain(): [string, string, string][] {
  const g = process.env.GEMINI_API_KEY, q = process.env.GROQ_API_KEY;
  const models = (process.env.FINN_CHAT_MODELS ||
    "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.1-flash-lite,gemini-2.5-flash,gemini-flash-latest").split(",");
  const out: [string, string, string][] = [];
  if (g) for (const m of models) out.push([GEMINI, g, m.trim()]);
  if (q) out.push([GROQ, q, process.env.FINN_CHAT_GROQ || "openai/gpt-oss-20b"]);
  return out;
}

export default async function handler(req: any, res: any) {
  if (req.method === "GET") return res.status(200).json({ ai: chain().length > 0 });
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  const models = chain();
  if (!models.length) return res.status(503).json({ error: "no model key configured" });

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
  const context = String(body.context || "").slice(0, 24000);
  const history: M[] = (Array.isArray(body.messages) ? body.messages : [])
    .filter((m: any) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
    .slice(-12)
    .map((m: any) => ({ role: m.role, content: m.content.slice(0, 2000) }));
  if (!history.length || history[history.length - 1].role !== "user") return res.status(400).json({ error: "no question" });

  const messages = [{ role: "system", content: `${SYSTEM}\n\nCONTEXT\n${context}` }, ...history];
  let last = "";
  for (const [url, key, model] of models) {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages, max_tokens: 700, temperature: 0.2,
          ...(model.includes("gpt-oss") ? { reasoning_effort: "low" } : {}) }),
        signal: AbortSignal.timeout(20000),
      });
      if (!r.ok) { last = `${model}: ${r.status}`; continue; }
      const j: any = await r.json();
      const reply = j?.choices?.[0]?.message?.content?.trim();
      if (reply) return res.status(200).json({ reply, model });
      last = `${model}: empty`;
    } catch (e: any) {
      last = `${model}: ${e?.name || "error"}`;
    }
  }
  return res.status(502).json({ error: `all models failed (${last})` });
}
