"""One small client for every model call FINN makes, with routing, caching and a budget.

Routing (override any model with env vars; see .env.example):
  cheap    bulk work on short text: classify a filing, one-line summary, pull a name + role.
           Groq GPT-OSS 20B (fast, free), falls back to Gemini Flash-Lite on rate limits.
  extract  long documents where numbers must be read exactly: results tables, concall
           transcripts. Gemini Flash (1M context, so a whole transcript is one call).
  reason   the few calls that need judgment: promised-vs-delivered verdicts, bull/bear.
           Gemini Flash with a stricter prompt; set FINN_REASON_MODEL to a Pro model if you
           have quota.

Both providers expose an OpenAI-compatible /chat/completions endpoint, so one code path
serves both. Every response is cached on disk by (model, prompt), so re-running a refresh
never pays twice for the same filing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .config import ROOT

log = logging.getLogger(__name__)


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (no extra dependency). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0]  # allow "KEY=value   # comment"
        if v.strip():
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
}


def _route(tier: str) -> list[tuple[str, str]]:
    """(provider, model) chain for a tier. First one with a key wins; the rest are fallbacks."""
    e = os.environ.get
    # Each Gemini model has its own free daily quota, so a chain of them goes a long way.
    flash = [("gemini", e("FINN_EXTRACT_MODEL", "gemini-3.5-flash")),
             ("gemini", e("FINN_EXTRACT_MODEL_2", "gemini-2.5-flash")),
             ("gemini", e("FINN_EXTRACT_MODEL_3", "gemini-flash-latest"))]
    lite = [("gemini", e("FINN_LITE_MODEL", "gemini-3.5-flash-lite")),
            ("gemini", e("FINN_LITE_MODEL_2", "gemini-3.1-flash-lite"))]
    groq_big = [("groq", e("FINN_EXTRACT_FALLBACK", "openai/gpt-oss-120b"))]
    chains = {
        "cheap": [("groq", e("FINN_CHEAP_MODEL", "openai/gpt-oss-20b"))] + lite,
        # Results numbers: Gemini only. A wrong revenue figure is worse than "open the filing".
        "numbers": flash + lite,
        "extract": flash + lite + groq_big,
        "reason": [("gemini", e("FINN_REASON_MODEL", "gemini-3.5-flash")), flash[1]] + groq_big,
    }
    return chains[tier]


class LLMUnavailable(RuntimeError):
    pass


class QuotaExhausted(RuntimeError):
    """A daily (not per-minute) free-tier quota is used up: waiting won't help today."""


EXHAUSTED: set[str] = set()  # models out of daily quota for the rest of this process


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, tin: int, tout: int) -> None:
        self.calls += 1
        self.tokens_in += tin
        self.tokens_out += tout
        m = self.by_model.setdefault(model, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
        m["calls"] += 1
        m["tokens_in"] += tin
        m["tokens_out"] += tout

    def as_dict(self) -> dict:
        return {"calls": self.calls, "cached": self.cached, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "by_model": self.by_model}


def parse_json(text: str):
    """Models sometimes wrap JSON in ``` fences or add a sentence; take the outermost object."""
    if text is None:
        raise ValueError("empty response")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


class LLM:
    """`llm.json(tier, system, user)` -> parsed dict, or raises LLMUnavailable.

    dry_run=True never touches the network: it logs what would be sent and returns None,
    so you can see the call plan (and token estimate) before spending anything.
    max_calls caps paid (non-cached) calls per run.
    """

    def __init__(self, cache_dir: Path = ROOT / ".cache" / "llm", dry_run: bool = False,
                 max_calls: int | None = None, timeout: int = 75, session=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dry_run, self.max_calls, self.timeout = dry_run, max_calls, timeout
        self.session = session or requests.Session()
        self.usage = Usage()
        self.planned: list[dict] = []

    def available(self, tier: str) -> bool:
        return any(os.environ.get(PROVIDERS[p][1]) for p, _ in _route(tier))

    def json(self, tier: str, system: str, user: str, max_tokens: int = 1500,
             temperature: float = 0.0):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        chain = [(p, m) for p, m in _route(tier) if os.environ.get(PROVIDERS[p][1])]
        if self.dry_run:
            est = (len(system) + len(user)) // 4
            self.planned.append({"tier": tier, "model": chain[0][1] if chain else None, "est_tokens_in": est})
            return None
        if not chain:
            raise LLMUnavailable(f"no API key for tier '{tier}' (set GROQ_API_KEY / GEMINI_API_KEY)")

        last: Exception | None = None
        for provider, model in chain:
            if model in EXHAUSTED:
                continue
            key = hashlib.sha1(json.dumps([model, messages, max_tokens]).encode()).hexdigest()
            path = self.cache_dir / f"{key}.json"
            if path.exists():
                try:
                    self.usage.cached += 1
                    return parse_json(json.loads(path.read_text(encoding="utf-8"))["content"])
                except (ValueError, KeyError):
                    path.unlink(missing_ok=True)
            if self.max_calls is not None and self.usage.calls >= self.max_calls:
                raise LLMUnavailable(f"call budget of {self.max_calls} reached")
            try:
                content = self._post(provider, model, messages, max_tokens, temperature, tier)
                try:
                    data = parse_json(content)
                except ValueError:  # one malformed answer: ask the same model once more, stricter
                    log.info("%s returned malformed JSON, retrying once", model)
                    retry = messages + [{"role": "assistant", "content": content[:2000]},
                                        {"role": "user", "content": "That was not valid JSON. Return the complete "
                                         "answer again as one valid JSON object; escape any double quotes inside strings."}]
                    content = self._post(provider, model, retry, max_tokens, temperature, tier)
                    data = parse_json(content)
                path.write_text(json.dumps({"model": model, "content": content}), encoding="utf-8")
                return data
            except QuotaExhausted as e:
                EXHAUSTED.add(model)
                log.warning("%s/%s: daily quota used up, skipping it for this run", provider, model)
                last = e
            except Exception as e:  # rate limit, bad JSON, outage: try the next model in the chain
                if "404" in str(e):
                    EXHAUSTED.add(model)  # model not served to this key; don't retry it this run
                log.warning("%s/%s failed: %s", provider, model, str(e)[:200])
                last = e
        raise LLMUnavailable(f"all models failed for tier '{tier}': {last}")

    def _post(self, provider: str, model: str, messages: list, max_tokens: int, temperature: float,
              tier: str = "cheap", retries: int = 5) -> str:
        url, key_env = PROVIDERS[provider]
        body = {"model": model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "response_format": {"type": "json_object"}}
        # Thinking models spend output tokens on reasoning before the answer. Keep thinking short
        # (copying numbers or summarising doesn't need it) and leave headroom so JSON isn't cut off.
        thinking = ("gpt-oss" in model or "qwen3" in model) if provider == "groq" else \
            (provider == "gemini" and "lite" not in model)
        if thinking:
            body["reasoning_effort"] = "medium" if tier == "reason" else "low"
            body["max_tokens"] = max_tokens + 2048
        headers = {"Authorization": f"Bearer {os.environ[key_env]}", "Content-Type": "application/json"}
        for attempt in range(retries):
            r = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            if r.status_code == 429 and _daily_quota(r):
                raise QuotaExhausted(model)
            if r.status_code == 429 and attempt < retries - 1:
                wait = float(r.headers.get("retry-after") or 0) or 8 * (attempt + 1)
                log.info("%s rate-limited, waiting %.0fs", provider, min(wait, 60))
                time.sleep(min(wait, 60))
                continue
            r.raise_for_status()
            j = r.json()
            u = j.get("usage") or {}
            self.usage.add(model, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0))
            content = j["choices"][0]["message"].get("content")
            if not content:
                raise RuntimeError(f"empty answer (finish_reason={j['choices'][0].get('finish_reason')})")
            return content
        raise RuntimeError(f"{provider} kept rate-limiting")


def _daily_quota(r) -> bool:
    try:
        body = r.text or ""
    except Exception:
        return False
    return bool(re.search(r"per ?day|PerDay|requests per day|RPD|daily", body, re.I))


# --------------------------------------------------------------------------- web search
def tavily_search(query: str, max_results: int = 4, session=None, cache_dir: Path = ROOT / ".cache" / "tavily"):
    """Used only for push-side enrichment (who is the new CFO?). Never for research."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (hashlib.sha1(query.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    s = session or requests
    r = s.post("https://api.tavily.com/search", timeout=30,
               headers={"Authorization": f"Bearer {key}"},
               json={"api_key": key, "query": query, "max_results": max_results, "search_depth": "basic"})
    r.raise_for_status()
    results = [{"title": x.get("title"), "url": x.get("url"), "content": (x.get("content") or "")[:800]}
               for x in r.json().get("results", [])]
    path.write_text(json.dumps(results), encoding="utf-8")
    return results
