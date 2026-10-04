"""Provider-agnostic LLM client (plain HTTP, no SDKs).

Auto-detects a provider from environment variables:
  GEMINI_API_KEY / GOOGLE_API_KEY  -> Google Gemini
  GROQ_API_KEY                     -> Groq (OpenAI compatible)
  OPENAI_API_KEY                   -> OpenAI (or any OpenAI-compatible base via OPENAI_BASE_URL)
  CARTO_LLM=ollama                 -> local Ollama (CPU friendly, e.g. qwen2.5-coder:7b)
If none is configured the agent runs fully offline with its deterministic planner.
"""

from __future__ import annotations

import json
import os
import re
import time

import httpx

from . import config

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5-coder:7b",
}


class LLM:
    def __init__(self, provider: str | None = None, model: str | None = None):
        provider = (provider or config.LLM_PROVIDER or "auto").lower()
        if provider == "auto":
            if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
                provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                provider = "groq"
            elif os.getenv("OPENAI_API_KEY"):
                provider = "openai"
            else:
                provider = "none"
        self.provider = provider
        self.model = model or os.getenv("CARTO_LLM_MODEL") or DEFAULT_MODELS.get(provider, "")
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0}
        self.client = httpx.Client(timeout=60)

    @property
    def available(self) -> bool:
        return self.provider != "none"

    def describe(self) -> str:
        return f"{self.provider}:{self.model}" if self.available else "offline (deterministic planner)"

    # ------------------------------------------------------------------ chat
    def chat(self, system: str, messages: list[dict], json_mode: bool = True, temperature: float = 0.1) -> str:
        t0 = time.perf_counter()
        if self.provider == "gemini":
            out = self._gemini(system, messages, json_mode, temperature)
        elif self.provider in ("openai", "groq", "ollama"):
            out = self._openai_compat(system, messages, json_mode, temperature)
        else:
            raise RuntimeError("No LLM provider configured")
        self.usage["calls"] += 1
        self.usage["seconds"] += time.perf_counter() - t0
        return out

    def chat_json(self, system: str, messages: list[dict]) -> dict:
        raw = self.chat(system, messages, json_mode=True)
        return parse_json(raw)

    def _gemini(self, system, messages, json_mode, temperature) -> str:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages]
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": temperature, **({"responseMimeType": "application/json"} if json_mode else {})},
        }
        r = self.client.post(url, json=body, headers={"x-goog-api-key": key})
        r.raise_for_status()
        data = r.json()
        um = data.get("usageMetadata", {})
        self.usage["input_tokens"] += um.get("promptTokenCount", 0)
        self.usage["output_tokens"] += um.get("candidatesTokenCount", 0)
        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def _openai_compat(self, system, messages, json_mode, temperature) -> str:
        if self.provider == "groq":
            base, key = "https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY")
        elif self.provider == "ollama":
            base, key = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"), "ollama"
        else:
            base, key = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"), os.getenv("OPENAI_API_KEY")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self.client.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"},
                             timeout=180 if self.provider == "ollama" else 60)
        r.raise_for_status()
        data = r.json()
        u = data.get("usage", {})
        self.usage["input_tokens"] += u.get("prompt_tokens", 0)
        self.usage["output_tokens"] += u.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"LLM did not return JSON: {raw[:200]}")
