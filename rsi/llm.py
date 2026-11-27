"""Free-tier LLM clients (stdlib only) with failover, spacing and hard daily request caps.

Keys come from the environment only (never from the repository or logs):
  GEMINI_API_KEY (+ optional GEMINI_MODELS="gemini-2.5-flash,gemini-2.5-flash-lite", GEMINI_DAILY_CAP, GEMINI_MIN_INTERVAL)
  GROQ_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY (OpenAI-compatible; optional *_MODEL, *_DAILY_CAP)
Only PUBLIC problem statements and Lean code are ever sent.  The caps keep usage inside free tiers;
if a provider starts charging, it is the account's billing setting, not this code, that decides - keep billing disabled.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date


class LLMError(Exception):
    pass


class LLMBudget(LLMError):
    """Daily request cap reached for every configured provider."""


class Usage:
    def __init__(self, path):
        self.path = path

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
        except Exception:  # noqa: BLE001
            d = {}
        return d if d.get("date") == str(date.today()) else {"date": str(date.today()), "counts": {}}

    def count(self, provider):
        return self._load()["counts"].get(provider, 0)

    def reserve(self, provider, cap):
        d = self._load()
        if d["counts"].get(provider, 0) >= cap:
            raise LLMBudget(f"{provider}: daily cap {cap} reached")
        d["counts"][provider] = d["counts"].get(provider, 0) + 1
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(d, f)


def _post(url, payload, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class GeminiClient:
    name = "gemini"

    def __init__(self, key, usage, models=None, base=None, cap=200, min_interval=6.0):
        self.key, self.usage, self.cap, self.min_interval = key, usage, cap, min_interval
        self.models = models or ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
        self.base = (base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self._last = 0.0

    def complete(self, prompt, system=None, temperature=0.4, max_tokens=8192):
        last_err = None
        for model in self.models:
            for attempt in range(3):
                self.usage.reserve(self.name, self.cap)
                wait = self.min_interval - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
                body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
                if system:
                    body["systemInstruction"] = {"parts": [{"text": system}]}
                try:
                    out = _post(f"{self.base}/models/{model}:generateContent", body, {"x-goog-api-key": self.key})
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP {e.code}"
                    if e.code == 429:
                        time.sleep(min(60, 10 * (attempt + 1)))
                        continue
                    if e.code in (400, 404):
                        break                                    # model name unavailable -> next model
                    raise LLMError(f"gemini {last_err}") from None
                except Exception as e:  # noqa: BLE001
                    last_err = type(e).__name__
                    time.sleep(5)
                    continue
                parts = (((out.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
                text = "".join(p.get("text", "") for p in parts)
                if text.strip():
                    return text
                last_err = "empty response"
        raise LLMError(f"gemini failed ({last_err})")

    def list_models(self):
        req = urllib.request.Request(f"{self.base}/models?pageSize=200", headers={"x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=60) as r:
            return [m["name"].split("/")[-1] for m in json.loads(r.read().decode()).get("models", [])]


class OpenAICompatClient:
    def __init__(self, name, key, base, model, usage, cap=200, min_interval=3.0):
        self.name, self.key, self.base, self.model, self.usage, self.cap, self.min_interval = name, key, base.rstrip("/"), model, usage, cap, min_interval
        self._last = 0.0

    def complete(self, prompt, system=None, temperature=0.4, max_tokens=8192):
        for attempt in range(3):
            self.usage.reserve(self.name, self.cap)
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            try:
                out = _post(f"{self.base}/chat/completions", {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens},
                            {"Authorization": f"Bearer {self.key}"})
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(min(60, 10 * (attempt + 1)))
                    continue
                raise LLMError(f"{self.name} HTTP {e.code}") from None
            except Exception as e:  # noqa: BLE001
                time.sleep(5)
                continue
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if text.strip():
                return text
        raise LLMError(f"{self.name} failed")


class FailoverLLM:
    def __init__(self, clients):
        self.clients = clients

    @property
    def available(self):
        return bool(self.clients)

    def complete(self, prompt, system=None, temperature=0.4, max_tokens=8192):
        if not self.clients:
            raise LLMError("no LLM provider configured (set GEMINI_API_KEY)")
        budget_hits, last = 0, None
        for c in self.clients:
            try:
                return c.complete(prompt, system, temperature, max_tokens)
            except LLMBudget as e:
                budget_hits += 1
                last = e
            except LLMError as e:
                last = e
        if budget_hits == len(self.clients):
            raise LLMBudget("all providers reached their daily cap")
        raise LLMError(str(last))


def build_llm_from_env(usage_path=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    usage = Usage(usage_path or os.path.join(root, "memory", "llm_usage.json"))
    clients = []
    order = [x.strip() for x in os.environ.get("RSI_LLM_PROVIDERS", "gemini,groq,openrouter,mistral").split(",") if x.strip()]
    for p in order:
        key = os.environ.get(f"{p.upper()}_API_KEY")
        if not key:
            continue
        cap = int(os.environ.get(f"{p.upper()}_DAILY_CAP", "200"))
        if p == "gemini":
            models = [m.strip() for m in os.environ.get("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]
            clients.append(GeminiClient(key, usage, models, os.environ.get("GEMINI_BASE_URL"), cap, float(os.environ.get("GEMINI_MIN_INTERVAL", "6"))))
        else:
            defaults = {"groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
                        "openrouter": ("https://openrouter.ai/api/v1", "openrouter/free"),
                        "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest")}
            if p in defaults:
                clients.append(OpenAICompatClient(p, key, os.environ.get(f"{p.upper()}_BASE_URL", defaults[p][0]),
                                                  os.environ.get(f"{p.upper()}_MODEL", defaults[p][1]), usage, cap))
    return FailoverLLM(clients)


class MockLLM:
    """Test double: returns queued responses."""
    available = True

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def complete(self, prompt, system=None, temperature=0.4, max_tokens=8192):
        self.calls.append(prompt)
        if not self.responses:
            raise LLMError("mock exhausted")
        return self.responses.pop(0)
