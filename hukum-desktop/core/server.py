"""Local dashboard server (stdlib only). Listens on 127.0.0.1 only, requires the local access token (cookie or header),
rejects foreign Host/Origin headers, and exposes one JSON endpoint per dashboard action plus a Server-Sent-Events stream."""
import json
import mimetypes
import os
import secrets
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (store, events, permissions, winapi, apps, monitor, projects, agents, memory, notify, sysmon, tools, commander,
               automation, whatsapp, gateway, ai, screen)

UI_DIR = os.path.join(store.ROOT, "ui")
TOKEN_PATH = os.path.join(store.DATA_DIR, "token.txt")
ROUTES = {}
STARTED = time.time()


def token():
    if os.path.exists(TOKEN_PATH):
        t = open(TOKEN_PATH).read().strip()
        if len(t) >= 24:
            return t
    t = secrets.token_urlsafe(24)
    with open(TOKEN_PATH, "w") as f:
        f.write(t)
    return t


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


def _j(o):
    return json.dumps(o, ensure_ascii=False, default=str).encode()


# ---------------------------------------------------------------- overview
@route("GET", "/api/overview")
def overview(q, body):
    s = sysmon.sample()
    return {
        "system": {**{k: s[k] for k in ("cpu", "ram", "gpu", "gpu_temp", "battery", "net_down", "net_up") if k in s}, "summary": sysmon.describe(s),
                   "findings": sysmon.diagnose(s)},
        "monitor": monitor.status(), "observations": monitor.recent(8), "context": monitor.context(),
        "notifications": {"counts": notify.counts(), "recent": notify.recent(6, unacked=True)},
        "agents": agents.jobs(5), "tasks": memory.list_tasks(open_only=True)[:6],
        "approvals": permissions.pending(), "estop": permissions.estop_state(),
        "gateway": {**gateway.link_state(), "enabled": bool(store.get("gateway.link"))},
        "ai": {"available": ai.available(), "model": store.get("ai.model")},
        "uptime": int(time.time() - STARTED),
    }


@route("GET", "/api/ping")
def ping(q, body):
    return {"ok": True, "version": "1.0", "uptime": int(time.time() - STARTED)}


# ---------------------------------------------------------------- chat / tools
@route("POST", "/api/chat")
def chat(q, body):
    text = (body.get("text") or "").strip()
    cid = secrets.token_hex(4)

    def work():
        try:
            r = commander.handle(text, source="dashboard", actor="boss")
        except Exception as e:
            r = {"reply": f"Something went wrong: {type(e).__name__}: {e}", "steps": [], "via": "error"}
        events.emit("chat_reply", {"id": cid, "reply": r["reply"], "steps": [{k: v for k, v in s.items() if k != "data"} for s in r["steps"]], "via": r["via"]})
    threading.Thread(target=work, daemon=True).start()
    return {"id": cid}


@route("GET", "/api/chat/history")
def chat_history(q, body):
    return store.q("SELECT ts,role,text FROM conv ORDER BY id DESC LIMIT 60")[::-1]


@route("GET", "/api/tools")
def tools_list(q, body):
    return tools.catalog()


@route("POST", "/api/tools/call")
def tools_call(q, body):
    return tools.call(body["name"], body.get("args") or {}, actor="boss", source="dashboard")


@route("POST", "/api/briefing")
def briefing(q, body):
    return {"text": commander.briefing()}


# ---------------------------------------------------------------- settings
@route("GET", "/api/settings")
def settings_get(q, body):
    return store.describe()


@route("POST", "/api/settings")
def settings_set(q, body):
    v = store.set_(body["key"], body["value"])
    store.audit("boss", "setting", body["key"], "low", "allowed", "" if store.SPEC[body["key"]][2] == "secret" else str(body["value"])[:80])
    return {"ok": True, "value": v if store.SPEC[body["key"]][2] != "secret" else "(saved)"}


# ---------------------------------------------------------------- apps
@route("GET", "/api/apps")
def apps_get(q, body):
    return apps.status()


@route("POST", "/api/apps/action")
def apps_action(q, body):
    return tools.call({"launch": "app_launch", "focus": "app_focus", "close": "app_close"}[body["action"]],
                      {"name": body["name"], **({"path": body["path"]} if body.get("path") else {})}, actor="boss", source="dashboard")


@route("GET", "/api/windows")
def windows(q, body):
    out = []
    for w in winapi.list_windows():
        try:
            screen.check_allowed(w)
            private = False
        except screen.Blocked:
            private = True
        out.append({"hwnd": w["hwnd"], "app": w["name"], "title": "(private)" if private else w["title"], "minimized": w["minimized"], "foreground": bool(w.get("foreground"))})
    return out


# ---------------------------------------------------------------- monitor
@route("GET", "/api/monitor")
def monitor_get(q, body):
    return {"status": monitor.status(), "recent": monitor.recent(40), "context": monitor.context(), "detectors": [{"id": d[0], "severity": d[1], "title": d[3]} for d in monitor.DETECTORS]}


@route("POST", "/api/monitor/control")
def monitor_ctl(q, body):
    mode = body["mode"]
    if mode == "start":
        monitor.start(body.get("scope") or None)
    elif mode == "tick":
        monitor.tick(force=True)
    else:
        getattr(monitor, mode)()
    return monitor.status()


@route("POST", "/api/monitor/look")
def monitor_look(q, body):
    """One-off look at a window the user picks (with all privacy rules)."""
    return tools.call("screen_read", {"hwnd": int(body["hwnd"])}, actor="boss", source="dashboard")


# ---------------------------------------------------------------- projects
@route("GET", "/api/projects")
def projects_get(q, body):
    return {"projects": projects.list_projects() or projects.scan(), "servers": projects.dev_servers()}


@route("POST", "/api/projects/scan")
def projects_scan(q, body):
    return projects.scan()


@route("GET", "/api/servers")
def servers_get(q, body):
    return projects.dev_servers()


# ---------------------------------------------------------------- agents
@route("GET", "/api/agents")
def agents_get(q, body):
    return {"drivers": agents.drivers(), "jobs": agents.jobs(40)}


@route("POST", "/api/agents/run")
def agents_run(q, body):
    return tools.call("agent_run", {k: body.get(k) for k in ("agent", "project", "prompt", "readonly", "verify") if body.get(k) is not None}, actor="boss", source="dashboard")


@route("POST", "/api/agents/cancel")
def agents_cancel(q, body):
    return tools.call("agent_cancel", {"job_id": body["id"]}, actor="boss", source="dashboard")


@route("GET", "/api/agents/job")
def agents_job(q, body):
    return agents.get(q["id"][0])


# ---------------------------------------------------------------- tasks / memory
@route("GET", "/api/tasks")
def tasks_get(q, body):
    return memory.list_tasks()


@route("POST", "/api/tasks")
def tasks_add(q, body):
    return memory.add_task(body["title"], body.get("detail", ""), body.get("priority", 2), body.get("due", ""), body.get("project", ""))


@route("POST", "/api/tasks/update")
def tasks_update(q, body):
    return memory.update_task(body["id"], **{k: v for k, v in body.items() if k != "id"})


@route("POST", "/api/tasks/delete")
def tasks_delete(q, body):
    memory.delete_task(body["id"])
    return {"ok": True}


@route("GET", "/api/memory")
def memory_get(q, body):
    return memory.recall(q.get("q", [""])[0], limit=100)


@route("POST", "/api/memory")
def memory_add(q, body):
    return memory.remember(body["text"], body.get("kind", "fact"), body.get("project", ""), bool(body.get("pinned")))


@route("POST", "/api/memory/forget")
def memory_forget(q, body):
    memory.forget(body["id"])
    return {"ok": True}


@route("POST", "/api/memory/pin")
def memory_pin(q, body):
    memory.pin(body["id"], body.get("on", True))
    return {"ok": True}


# ---------------------------------------------------------------- notifications / activity / audit
@route("GET", "/api/notifications")
def notif_get(q, body):
    return {"items": notify.recent(100), "counts": notify.counts()}


@route("POST", "/api/notifications/ack")
def notif_ack(q, body):
    notify.ack_all() if body.get("all") else notify.ack(body["id"])
    return {"ok": True}


@route("POST", "/api/notifications/test")
def notif_test(q, body):
    return notify.notify(body.get("severity", "warning"), "Test notification", "This is a test from the Hukum dashboard.", key=f"test:{time.time()}", source="test", force=True)


@route("GET", "/api/activity")
def activity_get(q, body):
    kind, text = q.get("kind", [""])[0], q.get("q", [""])[0]
    sql, args = "SELECT * FROM activity WHERE 1=1", []
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if text:
        sql += " AND (text LIKE ? OR app LIKE ?)"
        args += [f"%{text}%", f"%{text}%"]
    return store.q(sql + " ORDER BY id DESC LIMIT 300", args)


@route("GET", "/api/audit")
def audit_get(q, body):
    return store.q("SELECT * FROM audit ORDER BY id DESC LIMIT 300")


@route("GET", "/api/approvals")
def approvals_get(q, body):
    return {"pending": permissions.pending(), "recent": store.q("SELECT * FROM approvals WHERE status!='pending' ORDER BY id DESC LIMIT 20")}


@route("POST", "/api/approvals/decide")
def approvals_decide(q, body):
    try:
        ok = permissions.approve(int(body["id"]), body.get("typed", "")) if body["decision"] == "approve" else permissions.reject(int(body["id"]))
        return {"ok": bool(ok)}
    except permissions.Denied as e:
        return {"ok": False, "error": str(e)}


@route("POST", "/api/quit")
def quit_(q, body):
    store.audit("boss", "quit", "tray/dashboard")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


@route("POST", "/api/estop")
def estop(q, body):
    if body.get("on"):
        permissions.estop("dashboard button")
        agents.cancel_all()
    else:
        permissions.release()
    return permissions.estop_state()


# ---------------------------------------------------------------- whatsapp
@route("GET", "/api/whatsapp")
def wa_get(q, body):
    st = {"phone_adb": whatsapp.phone_connected(), "gateway": gateway.status(), "history": whatsapp.history(30), "paused": store.get("msg.paused")}
    try:
        st["inbox"] = whatsapp.inbox()
    except Exception as e:
        st["inbox"] = f"(unavailable: {e})"
    return st


@route("GET", "/api/whatsapp/contacts")
def wa_contacts(q, body):
    try:
        return {"contacts": whatsapp.contacts(q.get("q", [""])[0])}
    except Exception as e:
        return {"contacts": [], "error": str(e)}


@route("POST", "/api/whatsapp/draft")
def wa_draft(q, body):
    return whatsapp.draft(body["contact"], body["text"])


@route("POST", "/api/whatsapp/send")
def wa_send(q, body):
    return tools.call("msg_send", {"contact": body["contact"], "text": body["text"], "route": body.get("route", "reply")}, actor="boss", source="dashboard")


# ---------------------------------------------------------------- automation
@route("GET", "/api/workflows")
def wf_get(q, body):
    return {"items": automation.list_all(), "runs": automation.runs(limit=20), "templates": automation.templates()}


@route("POST", "/api/workflows")
def wf_save(q, body):
    try:
        return automation.save(body["name"], body["spec"], body.get("enabled", True))
    except ValueError as e:
        return {"error": str(e)}


@route("POST", "/api/workflows/action")
def wf_action(q, body):
    wid = int(body["id"])
    a = body["action"]
    if a == "run":
        wf = automation.get(wid)
        automation.run_async(wf, "manual")
        return {"started": True}
    if a == "enable":
        automation.set_enabled(wid, True)
    elif a == "disable":
        automation.set_enabled(wid, False)
    elif a == "delete":
        automation.delete(wid)
    return {"ok": True}


# ---------------------------------------------------------------- system / integrations
@route("GET", "/api/system")
def system_get(q, body):
    s = sysmon.sample()
    return {"now": s, "summary": sysmon.describe(s), "findings": sysmon.diagnose(s), "history": sysmon.history(900), "top_cpu": sysmon.top_processes("cpu", 8),
            "top_mem": sysmon.top_processes("mem", 8), "servers": projects.dev_servers(), "internet": winapi.internet_ok()}


@route("POST", "/api/system/kill")
def system_kill(q, body):
    return tools.call("system_kill", {"pid": body["pid"]}, actor="boss", source="dashboard")


@route("GET", "/api/integrations")
def integrations(q, body):
    d = agents.drivers()
    return [
        {"id": "ai", "name": "AI model endpoint", "ok": ai.available(), "detail": f"{store.get('ai.base_url')} / {store.get('ai.model')}"},
        {"id": "gateway", "name": "Hukum gateway (phone link)", "ok": gateway.status().get("reachable", False), "detail": store.get("gateway.url")},
        {"id": "adb", "name": "Android phone (adb)", "ok": whatsapp.phone_connected()["connected"], "detail": store.get("adb.path")},
        *[{"id": k, "name": f"Agent: {k}", "ok": v["available"], "detail": v["mode"] + (" - " + v["note"] if v["note"] else "")} for k, v in d.items()],
    ]


@route("POST", "/api/integrations/test")
def integrations_test(q, body):
    t = body["id"]
    if t == "ai":
        try:
            r = ai.chat([{"role": "user", "content": "Reply with the single word OK."}], timeout=40)
            return {"ok": True, "detail": f"{r['model']} answered: {r['content'][:40]}"}
        except Exception as e:
            return {"ok": False, "detail": str(e)}
    if t == "gateway":
        return gateway.status()
    if t == "adb":
        return whatsapp.phone_connected()
    return {"ok": agents.drivers().get(t, {}).get("available", False)}


# ---------------------------------------------------------------- phone jobs (gateway job channel)
def execute_job(kind, args, jid):
    """Run a job that arrived from the phone. The phone's own approval counts as Boss's approval for low/medium/high risk
    actions; critical ones are refused here and must be done at the PC."""
    def go(tool, targs):
        risk = permissions.risk_of(tools.TOOLS[tool]["action"], {"command": targs.get("command", "")} if tool == "shell_run" else targs)
        if risk == "critical":
            raise permissions.Denied("critical actions cannot be started from the phone")
        r = tools.call(tool, targs, actor="phone", preapproved=True, source="phone")
        if not r["ok"]:
            raise RuntimeError(r["error"])
        return commander._fmt({"tool": tool}, r)
    if kind == "open":
        t = args["target"]
        return go("web_open", {"url": t}) if t.startswith("http") else go("app_launch", {"name": t})
    if kind == "read":
        r = tools.call("file_read", {"path": args["path"]}, actor="phone", preapproved=True, source="phone")
        if not r["ok"]:
            raise RuntimeError(r["error"])
        return r["result"]["text"]
    if kind == "run":
        return go("shell_run", {"command": args["command"], **({"cwd": args["cwd"]} if args.get("cwd") else {})})
    if kind == "stop":
        return go("agent_cancel", {"job_id": args.get("job") or "all"})
    if kind == "command":
        r = commander.handle(args.get("text", ""), source="phone", preapproved=True, actor="phone")
        return r["reply"]
    if kind == "code":
        res = tools.call("agent_run", {"agent": args.get("agent") or "antigravity", "project": args.get("repo") or "", "prompt": args.get("prompt", ""),
                                       "readonly": bool(args.get("readonly"))}, actor="phone", preapproved=True, source="phone")
        if not res["ok"]:
            raise RuntimeError(res["error"])
        job = res["result"]

        def watch():
            while True:
                time.sleep(3)
                j = agents.get(job["id"])
                if j["status"] in ("done", "failed", "cancelled"):
                    gateway.report(jid, "done" if j["status"] == "done" else "failed", f"{j['agent']} {j['status']}\n{j['output'][-2500:]}")
                    return
        threading.Thread(target=watch, daemon=True).start()
        return None
    raise ValueError(f"unknown job kind {kind}")


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Hukum"

    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype="application/json", extra=None):
        if isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            return False
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        cookie = self.headers.get("Cookie", "")
        got = self.headers.get("X-Token") or next((c.split("=", 1)[1] for c in cookie.split("; ") if c.startswith("hk_token=")), "")
        return secrets.compare_digest(got, self.server.token)

    def _handle(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html") and "t" in q and secrets.compare_digest(q["t"][0], self.server.token):
            return self._send(302, b"", extra={"Location": "/", "Set-Cookie": f"hk_token={self.server.token}; Path=/; HttpOnly; SameSite=Strict"})
        if not self._auth():
            return self._send(401, _j({"error": "unauthorized - open the dashboard with the link Hukum printed (it contains the access token)"}))
        if u.path.startswith("/api/"):
            if u.path == "/api/events":
                return self._sse(q)
            fn = ROUTES.get((method, u.path))
            if not fn:
                return self._send(404, _j({"error": "no such endpoint"}))
            body = {}
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 2_000_000:
                    return self._send(413, _j({"error": "too large"}))
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return self._send(400, _j({"error": "bad JSON"}))
            try:
                return self._send(200, _j(fn(q, body)))
            except KeyError as e:
                return self._send(400, _j({"error": f"missing field {e}"}))
            except (ValueError, LookupError, permissions.Denied) as e:
                return self._send(400, _j({"error": str(e)}))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, _j({"error": f"{type(e).__name__}: {e}"}))
        rel = "index.html" if u.path == "/" else u.path.lstrip("/")
        fp = os.path.abspath(os.path.join(UI_DIR, rel))
        if not fp.startswith(os.path.abspath(UI_DIR)) or not os.path.isfile(fp):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))

    def _sse(self, q):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = int(q.get("last", [events.latest_id()])[0])
        try:
            while True:
                evs = events.since(last, wait=15)
                if not evs:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                for e in evs:
                    last = e["id"]
                    self.wfile.write(f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e['data'], default=str)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make(port=8790):
    srv = Server(("127.0.0.1", port), Handler)
    srv.token = token()
    return srv
