"""Tool registry. Every capability Hukum has is a tool here: name, description, parameters, the permission action it maps to
and a handler that does the REAL thing and returns something verifiable. Callers (commander, HTTP API, automations, phone
jobs) use call(), which routes through permissions.run so risk, approvals, emergency stop and the audit log always apply."""
import os
import subprocess
import time
import webbrowser

from . import store, permissions, winapi, apps, uia, screen, sysmon, projects, agents, memory, notify, monitor, whatsapp, gateway

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
TOOLS = {}


def tool(name, action, desc, params=None, summary=None):
    def deco(fn):
        TOOLS[name] = {"name": name, "action": action, "desc": desc, "params": params or {}, "fn": fn, "summary": summary}
        return fn
    return deco


def _in_allowed(path):
    p = os.path.abspath(path).lower()
    return any(p == os.path.abspath(r).lower() or p.startswith(os.path.abspath(r).lower() + os.sep) for r in store.get_list("folders.allowed"))


def _window(app=None, hwnd=None):
    if hwnd:
        w = winapi.window_info(int(hwnd))
        if w:
            return w
    prof = apps.resolve(app) if app else None
    if app and not prof:
        # fall back to a title substring
        for w in winapi.list_windows():
            if app.lower() in w["title"].lower() or app.lower() in w["name"].lower():
                return w
        raise LookupError(f"no window or app matches '{app}'")
    ws = apps.windows_of(prof) if prof else []
    if not ws and not app:
        fg = winapi.foreground()
        if fg:
            return fg
    if not ws:
        raise LookupError(f"{app} has no open window")
    return next((w for w in ws if w.get("foreground")), ws[0])


# ---------------------------------------------------------------- apps
@tool("app_list", "app.list", "List known apps with running state, windows, CPU and memory")
def app_list():
    return apps.status()


@tool("app_launch", "app.launch", "Launch an app (optionally open a folder, file or URL in it)", {"name": "app name", "path": "optional folder/file/url"},
      summary=lambda a: f"Launch {a.get('name')}" + (f" with {a['path']}" if a.get("path") else ""))
def app_launch(name, path=None):
    if path and not str(path).startswith(("http://", "https://")) and not _in_allowed(path):
        raise permissions.Denied(f"{path} is outside the allowed folders")
    return apps.launch(name, path)


@tool("app_focus", "app.focus", "Bring an app's window to the front (verified)", {"name": "app name"})
def app_focus(name):
    return apps.focus(name)


@tool("app_close", "app.close", "Politely close an app's windows (it may ask to save; nothing is force-killed)", {"name": "app name"},
      summary=lambda a: f"Close {a.get('name')}")
def app_close(name=None, hwnd=None):
    return apps.close(name=name, hwnd=int(hwnd)) if hwnd else apps.close(name)


# ---------------------------------------------------------------- UI
@tool("ui_read", "ui.read", "Read the text visible in an app window (UI Automation, no screenshot)", {"app": "app or window title"})
def ui_read(app=None, hwnd=None):
    w = _window(app, hwnd)
    screen.check_allowed(w)
    return {"app": w["name"], "title": w["title"], "text": uia.read_text(w["hwnd"], 12000)}


@tool("ui_type", "ui.type", "Type text into an app (focuses it first, then verifies the foreground window)", {"app": "app", "text": "text to type"},
      summary=lambda a: f"Type {len(str(a.get('text', '')))} characters into {a.get('app')}")
def ui_type(app, text, hwnd=None):
    w = _window(app, hwnd)
    screen.check_allowed(w)
    f = apps.focus(hwnd=w["hwnd"])
    winapi.paste_text(text) if len(text) > 40 else winapi.type_text(text)
    time.sleep(0.4)
    return {"typed_into": w["title"], "foreground": f["foreground_now"], "verified": True}


@tool("ui_keys", "ui.keys", "Press a key combination such as ctrl+s or alt+f4 in an app", {"app": "app", "keys": "e.g. ctrl+s"})
def ui_keys(app, keys, hwnd=None):
    w = _window(app, hwnd)
    apps.focus(hwnd=w["hwnd"])
    winapi.press(keys)
    return {"pressed": keys, "in": w["title"]}


@tool("ui_click", "ui.click", "Press a named control in an app window (button, tab, menu item)", {"app": "app", "control": "control name"},
      summary=lambda a: f"Click '{a.get('control')}' in {a.get('app')}")
def ui_click(app, control, hwnd=None):
    w = _window(app, hwnd)
    screen.check_allowed(w)
    return uia.press(w["hwnd"], name=control)


@tool("screen_read", "screen.ocr", "Capture an app window and read it with local OCR (honours privacy exclusions)", {"app": "app or window title"})
def screen_read(app=None, hwnd=None):
    w = _window(app, hwnd)
    screen.check_allowed(w)
    png, wd, h = screen.capture_window(w["hwnd"])
    return {"app": w["name"], "title": w["title"], "size": f"{wd}x{h}", "text": screen.ocr_png(png)}


@tool("screen_capture", "screen.capture", "Capture an app window and save it as a PNG", {"app": "app"})
def screen_capture(app=None, hwnd=None):
    w = _window(app, hwnd)
    screen.check_allowed(w)
    png, wd, h = screen.capture_window(w["hwnd"])
    return {"path": screen.save(png, w["name"], w["title"], keep=True), "size": f"{wd}x{h}"}


# ---------------------------------------------------------------- system / files / shell / web
@tool("system_status", "system.read", "Current CPU, RAM, GPU, disks, battery in plain language")
def system_status():
    s = sysmon.sample()
    return {"summary": sysmon.describe(s), "findings": sysmon.diagnose(s), "top_cpu": sysmon.top_processes("cpu", 5), "top_mem": sysmon.top_processes("mem", 5)}


@tool("system_kill", "system.kill", "End a process by PID (high risk)", {"pid": "process id"}, summary=lambda a: f"Kill process {a.get('pid')}")
def system_kill(pid):
    winapi.kill_pid(int(pid))
    time.sleep(0.5)
    return {"killed": int(pid), "still_running": any(p["pid"] == int(pid) for p in winapi.processes(False))}


@tool("file_read", "file.read", "Read a text file inside the allowed folders", {"path": "file path", "max_chars": "limit"})
def file_read(path, max_chars=6000):
    if not _in_allowed(path):
        raise permissions.Denied(f"{path} is outside the allowed folders")
    low = os.path.basename(path).lower()
    if low.startswith(".env") or any(k in low for k in ("secret", "id_rsa", "credential", "password")):
        raise permissions.Denied("secret-looking files are never read")
    from .redact import redact
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return {"path": path, "text": redact(f.read(int(max_chars)))}


@tool("file_write", "file.write", "Write a text file inside the allowed folders", {"path": "file path", "text": "contents"},
      summary=lambda a: f"Write {a.get('path')} ({len(str(a.get('text', '')))} chars)")
def file_write(path, text):
    if not _in_allowed(path):
        raise permissions.Denied(f"{path} is outside the allowed folders")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"path": path, "bytes": os.path.getsize(path)}


@tool("shell_run", "shell.run", "Run a shell command in a project folder (risk is classified from the command)", {"command": "command", "cwd": "folder"},
      summary=lambda a: f"Run: {a.get('command')} (in {a.get('cwd') or 'D:\\\\learn'})")
def shell_run(command, cwd=None):
    cwd = cwd or (store.get_list("folders.allowed") or ["."])[0]
    if not _in_allowed(cwd):
        raise permissions.Denied(f"{cwd} is outside the allowed folders")
    from .redact import redact
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=int(store.get("shell.timeout_s")), creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return {"exit_code": r.returncode, "output": redact((r.stdout + r.stderr)[-6000:])}


@tool("web_open", "web.open", "Open a URL in the browser", {"url": "http(s) URL"})
def web_open(url):
    if not str(url).startswith(("http://", "https://")):
        raise ValueError("only http(s) URLs")
    webbrowser.open(url)
    return {"opened": url}


# ---------------------------------------------------------------- projects & agents
@tool("project_list", "file.read", "List detected projects with language, framework and git state")
def project_list():
    ps = projects.list_projects() or projects.scan()
    return [{"name": p["name"], "path": p["path"], "summary": projects.summary(p), "dirty": (p.get("git") or {}).get("dirty", 0)} for p in ps]


@tool("project_info", "file.read", "Full detail of one project (stack, scripts, ports, env key names, git)", {"project": "name"})
def project_info(project):
    p = projects.get(project)
    if not p:
        raise LookupError(f"no project named '{project}'")
    return projects.refresh(p["path"])


@tool("dev_servers", "system.read", "Running development servers (ports, process, project)")
def dev_servers():
    return projects.dev_servers()


@tool("agent_run", "agent.run", "Give a coding task to an AI agent (codex, antigravity, claude)",
      {"agent": "codex|antigravity|claude", "project": "project name or path", "prompt": "task", "readonly": "bool", "verify": "optional command to check the result"},
      summary=lambda a: f"{a.get('agent')} on {a.get('project')}: {str(a.get('prompt'))[:120]}")
def agent_run(agent, project, prompt, readonly=False, verify="", deps=None):
    p = projects.get(project)
    repo = p["path"] if p else project
    return agents.submit(agent, repo, prompt, readonly=bool(readonly), verify=verify or "", deps=deps)


@tool("agent_status", "agent.control", "Status and output of coding-agent jobs", {"job_id": "optional job id"})
def agent_status(job_id=None):
    if job_id:
        return agents.get(job_id)
    return {"drivers": agents.drivers(), "jobs": [{k: j[k] for k in ("id", "agent", "repo", "status", "prompt")} for j in agents.jobs(10)]}


@tool("agent_cancel", "agent.control", "Cancel a coding-agent job (or all)", {"job_id": "job id or 'all'"})
def agent_cancel(job_id):
    return {"cancelled": agents.cancel_all() if str(job_id) == "all" else agents.cancel(job_id)}


# ---------------------------------------------------------------- memory / tasks / notifications / monitoring
@tool("remember", "memory.write", "Remember a fact, preference or decision", {"text": "what to remember", "kind": "fact|pref|decision|objective"})
def remember(text, kind="fact"):
    return memory.remember(text, kind)


@tool("recall", "memory.write", "Search memory", {"query": "words"})
def recall(query=""):
    return memory.recall(query)


@tool("task_add", "task.write", "Add a task", {"title": "title", "due": "YYYY-MM-DD optional", "project": "optional", "priority": "1-3"})
def task_add(title, due="", project="", priority=2, detail=""):
    return memory.add_task(title, detail, priority, due, project)


@tool("task_list", "task.write", "List open tasks")
def task_list():
    return memory.list_tasks(open_only=True)


@tool("task_done", "task.write", "Mark a task done", {"id": "task id"})
def task_done(id):
    return memory.update_task(id, status="done")


@tool("notify", "notify", "Raise a notification", {"title": "title", "body": "text"})
def notify_(title, body="", severity="info"):
    return notify.notify(severity, title, body, source="user", force=True)


@tool("monitor_control", "monitor.control", "start | pause | resume | stop screen monitoring", {"mode": "start|pause|resume|stop"})
def monitor_control(mode):
    getattr(monitor, mode)()
    return monitor.status()


@tool("monitor_status", "monitor.control", "What monitoring is doing and what it has noticed lately")
def monitor_status():
    return {"status": monitor.status(), "recent": monitor.recent(10), "context": monitor.context()}


# ---------------------------------------------------------------- messages
@tool("msg_inbox", "msg.read", "Recent WhatsApp/notification messages captured by the phone")
def msg_inbox():
    return {"text": whatsapp.inbox()}


@tool("msg_draft", "msg.draft", "Draft a message (does not send)", {"contact": "who", "text": "message"})
def msg_draft(contact, text):
    return whatsapp.draft(contact, text)


@tool("msg_send", "msg.send", "Send a WhatsApp message through the phone (always shows the exact text for approval)",
      {"contact": "name or number", "text": "message", "route": "reply|new"},
      summary=lambda a: f"SEND to {a.get('contact')}: \"{str(a.get('text'))[:200]}\"")
def msg_send(contact, text, route="reply"):
    digits = "".join(c for c in str(contact) if c.isdigit())
    if route == "new" or len(digits) >= 10:
        return {"result": whatsapp.send_new(contact, text)}
    return {"result": whatsapp.reply(contact, text)}


def catalog():
    out = []
    for t in TOOLS.values():
        risk = permissions.ACTIONS.get(t["action"], ("medium",))[0]
        out.append({"name": t["name"], "desc": t["desc"], "params": t["params"], "risk": risk, "action": t["action"]})
    return out


def call(name, args=None, actor="hukum", preapproved=False, source="local"):
    """Run a tool through the permission manager. Returns {ok, result|error, risk, tool}."""
    t = TOOLS.get(name)
    if not t:
        return {"ok": False, "tool": name, "error": f"unknown tool '{name}'"}
    args = dict(args or {})
    summ = t["summary"](args) if t["summary"] else f"{t['desc']} {args if args else ''}".strip()
    risk = permissions.risk_of(t["action"], {"command": args.get("command", "")} if name == "shell_run" else args)
    try:
        res = permissions.run(actor, t["action"], args, lambda: t["fn"](**args), summary=summ, preapproved=preapproved, source=source)
        return {"ok": True, "tool": name, "risk": risk, "result": res}
    except permissions.Denied as e:
        return {"ok": False, "tool": name, "risk": risk, "denied": True, "error": str(e)}
    except screen.Blocked as e:
        return {"ok": False, "tool": name, "risk": risk, "denied": True, "error": f"privacy: {e}"}
    except TypeError as e:
        return {"ok": False, "tool": name, "risk": risk, "error": f"bad arguments: {e}"}
    except Exception as e:
        return {"ok": False, "tool": name, "risk": risk, "error": f"{type(e).__name__}: {e}"[:400]}
