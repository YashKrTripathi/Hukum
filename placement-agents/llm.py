"""One place for LLM calls.
Priority: local/own server (LLM_BASE_URL, e.g. Ollama's OpenAI-compatible API) -> OpenRouter -> Anthropic."""
import os
import httpx
from config import OPENROUTER_KEY, OPENROUTER_MODEL, ANTHROPIC_KEY, MODEL

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")        # e.g. http://127.0.0.1:11435/v1
LLM_MODEL = os.getenv("LLM_MODEL", "hukum-brain")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_REASONING = os.getenv("LLM_REASONING", "low")               # gpt-oss: low keeps replies fast


def available() -> bool:
    return bool(LLM_BASE_URL or OPENROUTER_KEY or ANTHROPIC_KEY)


def _endpoint():
    """(url, headers, model, extra_body) of the chat-completions API to use, or None for Anthropic."""
    if LLM_BASE_URL:
        return (LLM_BASE_URL + "/chat/completions", {"Authorization": f"Bearer {LLM_API_KEY}"},
                LLM_MODEL, {"reasoning_effort": LLM_REASONING} if LLM_REASONING else {})
    if OPENROUTER_KEY:
        return ("https://openrouter.ai/api/v1/chat/completions",
                {"Authorization": f"Bearer {OPENROUTER_KEY}"}, OPENROUTER_MODEL, {})
    return None


def chat_raw(messages: list, tools: list | None = None, max_tokens: int = 700) -> dict:
    """Chat with optional function calling. Returns the assistant message dict."""
    ep = _endpoint()
    if not ep:
        raise RuntimeError("Set LLM_BASE_URL (own server) or OPENROUTER_API_KEY in .env to talk to the agent")
    url, headers, model, extra = ep
    body = {"model": model, "max_tokens": max_tokens, "messages": messages, **extra}
    if tools:
        body["tools"] = tools
    r = httpx.post(url, headers=headers, json=body, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def chat(prompt: str, max_tokens: int = 300) -> str:
    ep = _endpoint()
    if ep:
        url, headers, model, extra = ep
        r = httpx.post(url, headers=headers, timeout=120,
                       json={"model": model, "max_tokens": max_tokens,
                             "messages": [{"role": "user", "content": prompt}], **extra})
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    import anthropic
    c = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    r = c.messages.create(model=MODEL, max_tokens=max_tokens,
                          messages=[{"role": "user", "content": prompt}])
    return r.content[0].text.strip()
