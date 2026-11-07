"""Hukum API server (stdlib only). Used by the Android app and the web voice page.
All /api calls except /api/ping need the secret key in the X-Key header.
  POST /api/chat         {"text"}                  -> {"text","speech"}
  POST /api/tts          {"text"}                  -> audio/mpeg (natural neural voice)
  GET  /api/events?since=N   long-poll (25 s)      -> {"events":[{id,type,text}], "last":N}   (rings the phone)
  POST /api/phone_state  {"state","app"}           -> phone watcher (study | distract | idle | other)
  GET  /                  web voice page (PWA)"""
import asyncio
import json
import mimetypes
import os
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import db
import chat_agent
import pcbridge

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
PORT = int(os.getenv("WEB_PORT", "8765"))
OPEN_PROMPT = ("(Boss just opened the app. Greet him in ONE short Hinglish sentence. If the inbox has unanswered "
               "messages, mention the most important one; otherwise just ask what he needs.)")
RING_PROMPT = ("(You just rang Yash's phone and he answered. The reason for the call: {reason}. "
               "Start the conversation about that, in Hinglish, 1-2 short sentences, firm but friendly.)")

# ---- events pushed to the phone (ring screen) ----
_events: list = []
_next_id = 1
_cv = threading.Condition()
PHONE = ("none", 0.0, "")      # (state, unix time, app) last report from the Android app


def push_event(kind: str, text: str = ""):
    global _next_id
    with _cv:
        _events.append({"id": _next_id, "type": kind, "text": text, "ts": time.time()})
        _next_id += 1
        del _events[:-50]
        _cv.notify_all()


pcbridge.set_push(push_event)


def key() -> str:
    k = db.get("web_key")
    if not k:
        k = secrets.token_urlsafe(18)
        db.put("web_key", k)
    return k


def link() -> str | None:
    base = db.get("web_url")
    return f"{base}/?k={key()}&talk=1" if base else None


def phone_state():
    """(state, app) if the phone reported in the last 3 minutes, else None."""
    s, ts, app = PHONE
    return (s, app) if time.time() - ts < 180 else None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authed(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Key", ""), key())

    def _pc_authed(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-PC-Key", ""), pcbridge.pc_key())

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/api/pc/poll":                      # the PC agent (its own key, not the phone key)
            if not self._pc_authed():
                return self._json(401, {"error": "unauthorized"})
            wait = min(25.0, float(parse_qs(u.query).get("wait", ["25"])[0]))
            return self._json(200, {"jobs": pcbridge.poll(wait)})
        if path == "/api/ping":
            return self._json(200, {"ok": True})
        if path == "/api/tools":
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            return self._json(200, {"tools": [t["function"] for t in chat_agent.TOOLS]})
        if path == "/api/events":
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            since = int(parse_qs(u.query).get("since", ["-1"])[0])
            with _cv:
                if since < 0:
                    return self._json(200, {"events": [], "last": _next_id - 1})
                deadline = time.time() + 25
                while not any(e["id"] > since for e in _events):
                    left = deadline - time.time()
                    if left <= 0:
                        break
                    _cv.wait(left)
                evs = [e for e in _events if e["id"] > since]
            return self._json(200, {"events": evs, "last": evs[-1]["id"] if evs else since})
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, name))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "json" in ctype else ""))

    def do_POST(self):
        if self.path == "/api/pc/result":
            if not self._pc_authed():
                return self._json(401, {"error": "unauthorized"})
            try:
                b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                ok = pcbridge.result(str(b.get("id", "")), str(b.get("status", "")), str(b.get("output", "")))
                return self._json(200, {"ok": ok})
            except Exception as e:
                return self._json(500, {"error": str(e)[:200]})
        if self.path not in ("/api/chat", "/api/tts", "/api/phone_state", "/api/tool", "/api/inbox"):
            return self._json(404, {})
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/tool":
                # Called by the Hermes MCP bridge: run a Hukum tool; phone actions go out as events.
                chat_agent._tl.actions = []
                result = chat_agent.run_tool(str(body.get("name", "")), body.get("args") or {})
                for act in chat_agent._tl.actions:
                    push_event("action", json.dumps(act, ensure_ascii=False))
                return self._json(200, {"result": result})
            if self.path == "/api/inbox":
                import inbox
                for m in (body.get("batch") or [body]):
                    if m.get("removed"):
                        inbox.removed(str(m["removed"]), str(m.get("reason", "")))
                    else:
                        inbox.add(str(m.get("app", "")), str(m.get("sender", "")), str(m.get("chat", "")),
                                  str(m.get("text", "")), float(m.get("ts") or 0) / 1000 or None,
                                  str(m.get("key", "")), bool(m.get("can_reply")))
                return self._json(200, {"ok": True})
            if self.path == "/api/phone_state":
                global PHONE
                PHONE = (str(body.get("state", "other")), time.time(), str(body.get("app", ""))[:60])
                return self._json(200, {"ok": True})
            text = str(body.get("text", "")).strip()[:2000]
            if self.path == "/api/tts":
                import voice
                out = os.path.join(tempfile.gettempdir(), f"hukum_tts_{threading.get_ident()}.mp3")
                asyncio.run(voice.speak(chat_agent.spoken(text) if body.get("rewrite") else text, out))
                with open(out, "rb") as f:
                    return self._send(200, f.read(), "audio/mpeg")
            if text == "__open__":
                text = OPEN_PROMPT
            elif text.startswith("__ring__:"):
                text = RING_PROMPT.format(reason=text[9:].strip())
            elif text.startswith("__wake__:"):
                text = chat_agent.WAKE_PROMPT.format(calls=text[9:].strip())
            try:
                import hermes_brain
            except ImportError:      # gateway on the CRM server has no Hermes
                class hermes_brain:      # noqa: N801
                    wants_hermes = staticmethod(lambda t: False)
                    ask = staticmethod(lambda t: None)
            reply = None
            actions = []
            if hermes_brain.wants_hermes(text):          # heavy/open-ended: Hermes does the thinking
                reply = hermes_brain.ask(text)
            if not reply:
                try:
                    reply, actions = chat_agent.respond_full(text)    # fast path (~2s)
                except Exception:
                    reply = hermes_brain.ask(text)                     # OpenRouter down: Hermes backs up
                    actions = []
                    if not reply:
                        raise
            speech = chat_agent.spoken(reply) if body.get("speech", True) else reply
            return self._json(200, {"text": reply, "speech": speech, "actions": actions})
        except Exception as e:
            return self._json(500, {"error": str(e)[:200]})


def start():
    srv = ThreadingHTTPServer((os.getenv("WEB_HOST", "0.0.0.0"), PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return PORT
