"""AI model router: OpenAI-compatible chat endpoints (UNISYNCAI/HINDVI, OpenRouter, Ollama /v1 ...) with a fallback
endpoint, secret redaction on everything sent, a context limit, and a local-only switch."""
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import store
from .redact import redact


def _is_local(url):
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_loopback or ip.is_private
    except Exception:
        return False


def providers():
    out = []
    for prefix, label in (("ai", "main"), ("ai.fallback", "fallback")):
        base = store.get(f"{prefix}.base_url").rstrip("/") if prefix == "ai" else store.get("ai.fallback_base_url").rstrip("/")
        model = store.get(f"{prefix}.model") if prefix == "ai" else store.get("ai.fallback_model")
        key = store.get(f"{prefix}.api_key") if prefix == "ai" else store.get("ai.fallback_api_key")
        if base and model:
            out.append({"label": label, "base": base, "model": model, "key": key})
    return out


def available():
    """True when at least one usable endpoint is configured (a key, or a local endpoint that needs none)."""
    for p in providers():
        if p["key"] or _is_local(p["base"]):
            if store.get("ai.local_only") and not _is_local(p["base"]):
                continue
            return True
    return False


def _trim(messages):
    limit = int(store.get("ai.context_chars"))
    msgs = [dict(m) for m in messages]
    total = sum(len(str(m.get("content") or "")) for m in msgs)
    while total > limit and len(msgs) > 2:
        drop = next((i for i, m in enumerate(msgs) if m.get("role") != "system"), None)
        if drop is None or drop >= len(msgs) - 1:
            break
        total -= len(str(msgs[drop].get("content") or ""))
        msgs.pop(drop)
    return msgs


def _call(p, messages, tools, timeout, json_mode):
    body = {"model": p["model"], "messages": messages, "temperature": float(store.get("ai.temperature")), "stream": False}
    eff = store.get("ai.reasoning")
    if eff and any(k in p["model"].lower() for k in ("hindvi", "gpt-oss", "o1", "o3", "o4")):
        body["reasoning_effort"] = eff
    if tools:
        body["tools"] = tools
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if p["key"]:
        headers["Authorization"] = "Bearer " + p["key"]
    req = urllib.request.Request(p["base"] + "/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    return {"content": msg.get("content") or "", "tool_calls": msg.get("tool_calls"), "model": data.get("model", p["model"]),
            "provider": p["label"], "usage": data.get("usage")}


def chat(messages, tools=None, timeout=90, json_mode=False):
    """Returns {content, tool_calls, model, provider}. Raises RuntimeError when no endpoint works."""
    clean = []
    for m in _trim(messages):
        m = dict(m)
        if isinstance(m.get("content"), str):
            m["content"] = redact(m["content"])
        clean.append(m)
    errors = []
    for p in providers():
        if store.get("ai.local_only") and not _is_local(p["base"]):
            errors.append(f"{p['label']}: blocked (local-only mode)")
            continue
        if not p["key"] and not _is_local(p["base"]):
            errors.append(f"{p['label']}: no API key")
            continue
        try:
            return _call(p, clean, tools, timeout, json_mode)
        except urllib.error.HTTPError as e:
            errors.append(f"{p['label']}: HTTP {e.code}")
        except Exception as e:
            errors.append(f"{p['label']}: {type(e).__name__}")
    raise RuntimeError("No AI endpoint answered (" + "; ".join(errors or ["none configured"]) + ")")


def ask_json(system, user, timeout=90):
    """Ask for a JSON object; tolerant of code fences. Returns a dict or raises."""
    r = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], timeout=timeout, json_mode=False)
    text = r["content"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("model did not return JSON")
    return json.loads(text[i:j + 1])
