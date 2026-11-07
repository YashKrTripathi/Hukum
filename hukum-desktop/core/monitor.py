"""Screen intelligence. A background worker looks at approved windows only, reads their text (UI Automation first,
OCR when a window exposes none), finds NEW lines since the last look, and runs detectors over them (build failed,
server crashed, waiting for input, agent finished ...). Everything it reports says whether it was OBSERVED (text on
screen) or INFERRED (a guess from patterns). Monitoring is off until started, visible in the dashboard, pausable,
limited to the apps in Settings, skips excluded windows, and backs off when the PC is busy."""
import hashlib
import re
import threading
import time

from . import store, events, winapi, uia, screen, notify, permissions
from .redact import redact

# id, severity, regex, title, what it means (inferred), app kinds it applies to (None = all)
DETECTORS = [
    ("npm_fail", "error", r"npm ERR!|ELIFECYCLE|Error: Cannot find module|UnhandledPromiseRejection", "An npm / Node command failed", "a Node process or npm script exited with an error", None),
    ("port_busy", "error", r"(?i)EADDRINUSE|address already in use|port \d+ is already in use", "A port is already in use", "another process holds the port your server wants", None),
    ("conn_refused", "warning", r"ECONNREFUSED|connection refused|Connection refused", "A connection was refused", "the service on the other end is down or the port is wrong", None),
    ("py_traceback", "error", r"Traceback \(most recent call last\)", "Python raised an exception", "a Python program crashed or logged an exception", None),
    ("ts_error", "error", r"error TS\d+", "TypeScript compile error", "the TypeScript build found type errors", None),
    ("build_fail", "error", r"(?i)build failed|compilation failed|failed to compile|BUILD FAILURE|Build error", "A build failed", "the build step did not finish successfully", None),
    ("test_fail", "warning", r"(?i)\b\d+ (tests? )?failed\b|\bFAILED\b \(|AssertionError|FAIL\s+\S+\.test", "Tests are failing", "at least one test failed", None),
    ("needs_input", "warning", r"\(y/n\)|\[Y/n\]|\[y/N\]|Press any key|Do you want to proceed|Continue\?|Enter to confirm", "A terminal is waiting for input", "a command is paused at a prompt", ["terminal"]),
    ("agent_permission", "warning", r"(?i)do you want to (allow|proceed|make this edit)|allow this (command|action|tool)|waiting for (your )?(approval|permission)|needs your permission|approve (this|the)", "A coding agent is waiting for permission", "an agent is paused until you approve something", ["coding-agent", "terminal", "editor"]),
    ("agent_done", "info", r"(?i)\b(task|work|implementation) (is )?(complete|completed|finished|done)\b|all (tasks|changes) (are )?(done|complete)|Worked for \d|✔ Done|Finished working", "A coding agent seems to have finished", "wording on screen suggests the agent completed its task", ["coding-agent", "terminal", "editor"]),
    ("agent_error", "error", r"(?i)\b(i|we) (couldn't|could not|was unable|were unable)\b|rate limit|usage limit|quota exceeded|overloaded_error|API Error", "A coding agent hit an error", "the agent reported a failure, limit or API error", ["coding-agent", "terminal"]),
    ("deploy_done", "info", r"(?i)deployment (complete|successful|succeeded)|successfully deployed|deployed to", "A deployment completed", "wording on screen says a deploy finished", None),
    ("server_up", "info", r"(?i)ready in \d+ ?ms|listening on (port )?\d+|Local:\s+https?://|Running on https?://|Server (started|running)", "A development server is running", "a server printed a startup message", ["terminal"]),
    ("browser_error", "warning", r"This site can.t be reached|ERR_[A-Z_]{5,}|502 Bad Gateway|503 Service|Internal Server Error|Application error", "A browser shows an error page", "the page in front of you is an error page", ["browser"]),
    ("ssh_down", "warning", r"(?i)ssh: connect to host .* (timed out|refused|unreachable)|Connection timed out|Network is unreachable", "A remote server looks unreachable", "an SSH or network command could not reach the host", None),
    ("docker_err", "warning", r"(?i)Cannot connect to the Docker daemon|docker: Error|container .* exited with code [1-9]", "Docker reported a problem", "Docker or a container failed", None),
]
_RX = [(d[0], d[1], re.compile(d[2]), d[3], d[4], d[5]) for d in DETECTORS]

_state = {"mode": "stopped", "started": 0.0, "passes": 0, "last_pass": 0.0, "skipped_busy": 0, "last_error": "", "scope": None}
_win = {}                 # hwnd -> {"lines": set, "hash": str, "checked": ts, "title": str}
_last_fg = {"key": None}
_recent = []              # last observations for the dashboard
_lock = threading.RLock()
_thread = None
_wake = threading.Event()
_servers_seen = {}


def kind_of(w):
    from . import apps
    for p in apps.PROFILES:
        if w["name"].lower() in [x.lower() for x in p["procs"]] or any(h in (w["exe"] or "").lower() for h in p["hints"] if h):
            return p["kind"], p["id"]
    return "app", w["name"].lower()


def detect(text, kind="app"):
    """Run the detectors over text; returns [{id,severity,title,meaning,line}] (one per detector, first matching line)."""
    found = []
    lines = text.splitlines()
    for did, sev, rx, title, meaning, kinds in _RX:
        if kinds and kind not in kinds:
            continue
        for ln in lines:
            if rx.search(ln):
                found.append({"id": did, "severity": sev, "title": title, "meaning": meaning, "line": redact(ln.strip())[:200]})
                break
    return found


def _in_schedule():
    sch = store.get("monitor.schedule").strip()
    m = re.fullmatch(r"(\d\d):(\d\d)-(\d\d):(\d\d)", sch)
    if not m:
        return True
    now = time.strftime("%H:%M")
    a, b = f"{m[1]}:{m[2]}", f"{m[3]}:{m[4]}"
    return (a <= now <= b) if a <= b else (now >= a or now <= b)


def _targets():
    mon_apps = [a.lower() for a in (_state["scope"] or store.get_list("monitor.apps"))]
    out = []
    for w in winapi.list_windows():
        if w["name"].lower() in mon_apps and w["pid"] != winapi.kernel32.GetCurrentProcessId():
            try:
                screen.check_allowed(w)
            except screen.Blocked:
                continue
            out.append(w)
    out.sort(key=lambda w: (not w.get("foreground"), _win.get(w["hwnd"], {}).get("checked", 0)))
    return out[:int(store.get("monitor.max_windows"))]


def read_window(w, allow_ocr=True):
    """Text of a window: (text, source) where source is 'uia' or 'ocr'."""
    text = ""
    try:
        text = uia.read_text(w["hwnd"], 30000)
    except Exception:
        text = ""
    if len(text.strip()) >= 20:
        return redact(text), "uia"
    if allow_ocr and store.get("monitor.use_ocr") and not w["minimized"]:
        png, _, _ = screen.capture_window(w["hwnd"])
        if store.get("monitor.keep_screenshots"):
            screen.save(png, w["name"], w["title"])
        return screen.ocr_png(png), "ocr"
    return redact(text), "uia"


def observe(w):
    """Look at one window now. Returns {new_lines:[...], findings:[...], source}. Updates per-window memory."""
    kind, app_id = kind_of(w)
    text, source = read_window(w)
    h = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
    st = _win.setdefault(w["hwnd"], {"lines": set(), "hash": "", "checked": 0, "title": "", "first": True})
    st["checked"] = time.time()
    st["title"] = w["title"]
    if h == st["hash"]:
        return {"new_lines": [], "findings": [], "source": source, "unchanged": True, "app": app_id, "kind": kind}
    st["hash"] = h
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    new = [ln for ln in lines if ln not in st["lines"]]
    first = st.pop("first", False)
    st["lines"] = set(lines[-400:]) | (st["lines"] if len(st["lines"]) < 400 else set())
    findings = detect("\n".join(new), kind) if not first or True else []
    return {"new_lines": new[:60], "findings": findings, "source": source, "app": app_id, "kind": kind}


def _report(w, res):
    kind = res["kind"]
    for f in res["findings"]:
        key = f"mon:{f['id']}:{w['name']}:{hashlib.md5(w['title'].encode()).hexdigest()[:6]}"
        body = (f"Observed on screen in {w['name']} ('{w['title'][:60]}'): {f['line']}  |  Inferred: {f['meaning']}.")
        notify.notify(f["severity"], f["title"], body, key=key, source="monitor")
        store.activity("detection", f"{f['title']} - {f['line']}", app=w["name"])
        _recent.append({"ts": time.time(), "app": w["name"], "title": f["title"], "severity": f["severity"], "observed": f["line"],
                        "inferred": f["meaning"], "source": res["source"]})
        del _recent[:-80]
        events.emit("observation", _recent[-1])


def _track_foreground():
    fg = winapi.foreground()
    if not fg:
        return
    key = (fg["name"], re.sub(r"\s+", " ", fg["title"])[:80])
    if key != _last_fg["key"]:
        _last_fg["key"] = key
        try:
            screen.check_allowed(fg)
            store.activity("focus", fg["title"], app=fg["name"])
        except screen.Blocked:
            store.activity("focus", "(private window)", app=fg["name"])


def _check_servers():
    try:
        from . import projects
        cur = {s["pid"]: s for s in projects.dev_servers()}
    except Exception:
        return
    for pid, s in list(_servers_seen.items()):
        if pid not in cur:
            notify.notify("warning", f"Dev server stopped: {s['project'] or s['name']}",
                          f"Observed: the process '{s['name']}' (pid {pid}) that was serving {s.get('ports') or 'a port'} is no longer running. "
                          f"Inferred: the server stopped or crashed.", key=f"srv:{pid}", source="monitor")
            store.activity("detection", f"dev server stopped: {s['project'] or s['name']}", app=s["name"], project=s["project"])
            del _servers_seen[pid]
    for pid, s in cur.items():
        if pid not in _servers_seen:
            _servers_seen[pid] = s


def tick(force=False):
    """One monitoring pass. Returns a short report (used by the loop and by tests)."""
    if not force:
        if _state["mode"] != "running":
            return {"skipped": "not running"}
        if not store.get("perm.monitoring"):
            return {"skipped": "monitoring permission is off"}
        if permissions.estop_state()["on"]:
            return {"skipped": "emergency stop"}
        if not _in_schedule():
            return {"skipped": "outside the schedule"}
        if winapi.cpu_percent() > int(store.get("system.cpu_limit_pct")) * 3:       # PC very busy: skip this pass
            _state["skipped_busy"] += 1
            return {"skipped": "system busy"}
    _track_foreground()
    seen = 0
    for w in _targets():
        try:
            res = observe(w)
            seen += 1
            if res["findings"]:
                _report(w, res)
        except screen.Blocked:
            continue
        except Exception as e:
            _state["last_error"] = f"{w['name']}: {type(e).__name__}: {e}"[:200]
    _check_servers()
    live = {w["hwnd"] for w in winapi.list_windows()}
    for h in [h for h in _win if h not in live]:
        del _win[h]
    _state["passes"] += 1
    _state["last_pass"] = time.time()
    return {"windows": seen}


def _loop():
    while _state["mode"] != "stopped":
        try:
            if _state["mode"] == "running":
                tick()
        except Exception as e:
            _state["last_error"] = repr(e)[:200]
        _wake.wait(max(3, int(store.get("monitor.interval_s"))))
        _wake.clear()


def start(scope=None):
    """Begin monitoring. scope: list of exe names to restrict to (default: Settings > Monitoring apps)."""
    global _thread
    if not store.get("perm.monitoring"):
        raise permissions.Denied("'perm.monitoring' is switched off in Settings")
    if permissions.estop_state()["on"]:
        raise permissions.Denied("Emergency stop is on")
    _state.update(mode="running", started=time.time(), scope=list(scope) if scope else None, last_error="")
    if not (_thread and _thread.is_alive()):
        _thread = threading.Thread(target=_loop, daemon=True, name="monitor")
        _thread.start()
    store.audit("user", "monitor.start", ",".join(scope or store.get_list("monitor.apps")))
    events.emit("monitor", status())
    _wake.set()


def pause():
    if _state["mode"] == "running":
        _state["mode"] = "paused"
    events.emit("monitor", status())


def resume():
    if _state["mode"] == "paused":
        if permissions.estop_state()["on"]:
            raise permissions.Denied("Emergency stop is on")
        _state["mode"] = "running"
        _wake.set()
    events.emit("monitor", status())


def stop():
    _state["mode"] = "stopped"
    _wake.set()
    _win.clear()
    events.emit("monitor", status())


def status():
    return {"mode": _state["mode"], "since": _state["started"] or None, "passes": _state["passes"], "last_pass": _state["last_pass"] or None,
            "scope": _state["scope"] or store.get_list("monitor.apps"), "interval_s": int(store.get("monitor.interval_s")),
            "watching": [{"app": v["title"][:50]} for v in _win.values()][:10], "skipped_busy": _state["skipped_busy"],
            "last_error": _state["last_error"], "schedule": store.get("monitor.schedule") or "always"}


def recent(limit=30):
    return list(reversed(_recent))[:limit]


permissions.on_estop(lambda: pause() if _state["mode"] == "running" else None)


def context():
    """What Boss seems to be doing now: foreground app/title, a project guess, and why (all marked inferred)."""
    try:
        fg = winapi.foreground()
    except OSError:                      # not on Windows (CI, tests)
        return {"app": None}
    if not fg:
        return {"app": None}
    try:
        screen.check_allowed(fg)
        title = fg["title"]
    except screen.Blocked:
        return {"app": fg["name"], "title": "(private window)", "project": None, "activity": f"using {fg['name']}", "inferred": True}
    project = None
    try:
        from . import projects
        low = title.lower()
        for p in projects.list_projects():
            if p["name"].lower() in low:
                project = p["name"]
                break
    except Exception:
        pass
    kind, app_id = kind_of(fg)
    verb = {"editor": "editing code", "coding-agent": "working with an AI coding agent", "terminal": "in a terminal",
            "browser": "browsing"}.get(kind, "using " + fg["name"])
    return {"app": fg["name"], "title": title, "kind": kind, "project": project,
            "activity": f"{verb}" + (f" on {project}" if project else ""), "inferred": True}
