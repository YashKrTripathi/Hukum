"""Storage: SQLite database + the settings registry.

Every setting is declared once in SETTINGS (type, range, choices, description). The dashboard renders its Settings
page from this registry and the backend reads values through `settings.get(key)` at the moment it needs them, so a
control in the UI really changes behaviour (nothing is decorative)."""
import contextlib
import json
import os
import sqlite3
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("HUKUM_DATA", os.path.join(ROOT, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------- settings registry
# kind: bool | int | float | str | choice | list (comma separated) | secret (stored in Windows Credential Manager)
SETTINGS = [
    # group, key, kind, default, extra, description
    ("AI", "ai.base_url", "str", "https://api.openai.com/v1", {}, "OpenAI-compatible endpoint (UNISYNCAI, OpenRouter, Ollama /v1 ...)"),
    ("AI", "ai.model", "str", "HINDVI", {}, "Model name sent to the endpoint"),
    ("AI", "ai.api_key", "secret", "", {}, "API key (stored in Windows Credential Manager, never in files or logs)"),
    ("AI", "ai.fallback_base_url", "str", "", {}, "Fallback endpoint if the main one fails (optional)"),
    ("AI", "ai.fallback_model", "str", "", {}, "Fallback model name"),
    ("AI", "ai.fallback_api_key", "secret", "", {}, "Fallback API key"),
    ("AI", "ai.reasoning", "choice", "low", {"choices": ["", "low", "medium", "high"]}, "Reasoning effort sent to models that support it"),
    ("AI", "ai.temperature", "float", 0.3, {"min": 0.0, "max": 2.0}, "Sampling temperature"),
    ("AI", "ai.context_chars", "int", 24000, {"min": 2000, "max": 400000}, "Maximum characters of context sent per request"),
    ("AI", "ai.local_only", "bool", False, {}, "Never send anything to a non-local endpoint (refuses cloud URLs)"),
    ("Permissions", "perm.screen", "bool", True, {}, "Allow screenshots and screen reading"),
    ("Permissions", "perm.keyboard", "bool", True, {}, "Allow typing and keyboard shortcuts"),
    ("Permissions", "perm.mouse", "bool", True, {}, "Allow mouse clicks and movement"),
    ("Permissions", "perm.files", "bool", True, {}, "Allow reading/writing files inside the allowed folders"),
    ("Permissions", "perm.terminal", "bool", True, {}, "Allow running shell commands"),
    ("Permissions", "perm.apps", "bool", True, {}, "Allow launching, focusing and closing applications"),
    ("Permissions", "perm.monitoring", "bool", True, {}, "Allow background screen monitoring (still needs Start)"),
    ("Permissions", "perm.messages", "bool", True, {}, "Allow drafting and sending messages through the phone"),
    ("Permissions", "confirm.medium", "choice", "ask", {"choices": ["ask", "auto"]}, "Medium-risk actions (edit files, run dev commands): ask or run automatically"),
    ("Permissions", "confirm.low", "choice", "auto", {"choices": ["auto", "ask"]}, "Low-risk actions (read, open apps): run automatically or ask"),
    ("Permissions", "folders.allowed", "list", "D:\\learn", {}, "Folders Hukum may read/write and index (comma separated)"),
    ("Permissions", "approval.timeout_s", "int", 600, {"min": 15, "max": 86400}, "Seconds an approval request waits before it expires"),
    ("Monitoring", "monitor.interval_s", "int", 10, {"min": 3, "max": 3600}, "Seconds between monitoring passes"),
    ("Monitoring", "monitor.apps", "list", "WindowsTerminal,Code,antigravity,claude,codex,chrome,msedge,powershell,cmd", {}, "Programs (exe names, comma separated) that monitoring may look at"),
    ("Monitoring", "monitor.exclude", "list", "KeePass,Bitwarden,1Password,LastPass,Authenticator", {}, "Programs never captured"),
    ("Monitoring", "monitor.exclude_titles", "list", "password,incognito,private browsing,bank,otp,payment,wallet,login,sign in,.env,secret,credential,id_rsa,passwd,token,vault", {}, "Window titles (substrings) never captured"),
    ("Monitoring", "monitor.max_windows", "int", 4, {"min": 1, "max": 30}, "Most windows examined per pass (limits CPU use)"),
    ("Monitoring", "monitor.use_ocr", "bool", True, {}, "Use OCR when a window exposes no text through UI Automation"),
    ("Monitoring", "monitor.keep_screenshots", "bool", False, {}, "Keep screenshot files (history). Off = only text observations are stored"),
    ("Monitoring", "monitor.alert_min_severity", "choice", "warning", {"choices": ["info", "warning", "error"]}, "Lowest severity that raises a notification"),
    ("Monitoring", "monitor.schedule", "str", "", {}, "Only monitor between these hours, e.g. 09:00-23:00 (empty = always)"),
    ("Notifications", "notify.cooldown_s", "int", 300, {"min": 10, "max": 86400}, "Same alert is grouped for this many seconds"),
    ("Notifications", "notify.toast", "bool", True, {}, "Show Windows tray notifications"),
    ("Notifications", "notify.speak", "bool", False, {}, "Speak important notifications (dashboard must be open)"),
    ("Notifications", "notify.phone", "bool", False, {}, "Also send errors to the phone through the Hukum gateway"),
    ("Communication", "gateway.url", "str", "http://crm.dypiu.ac.in:8765", {}, "Hukum gateway (the brain server that talks to the phone)"),
    ("Communication", "gateway.phone_key", "secret", "", {}, "Phone key of the gateway (for messages, status)"),
    ("Communication", "gateway.pc_key", "secret", "", {}, "PC key of the gateway (lets the phone send jobs to this PC)"),
    ("Communication", "gateway.link", "bool", False, {}, "Accept jobs from the phone through the gateway"),
    ("Communication", "msg.confirm", "bool", True, {}, "Always show the message and ask before sending"),
    ("Communication", "msg.trusted", "list", "", {}, "Trusted contacts that may be messaged without asking (comma separated)"),
    ("Communication", "adb.path", "str", "D:\\scrcpy-win32-v4.1\\adb.exe", {}, "adb.exe used to drive the Android phone (USB debugging)"),
    ("Communication", "msg.paused", "bool", False, {}, "Emergency pause for all outgoing messages"),
    ("Voice", "voice.enabled", "bool", True, {}, "Enable the microphone button in the dashboard"),
    ("Voice", "voice.wake", "bool", False, {}, "Listen for the wake word while the dashboard is open"),
    ("Voice", "voice.wake_word", "str", "hey hukum", {}, "Wake word"),
    ("Voice", "voice.speak_replies", "bool", True, {}, "Speak Hukum's replies"),
    ("Voice", "voice.rate", "float", 1.0, {"min": 0.5, "max": 2.0}, "Speaking speed"),
    ("Voice", "voice.voice", "str", "", {}, "Preferred voice name (empty = browser default)"),
    ("Voice", "voice.lang", "str", "en-IN", {}, "Recognition language"),
    ("System", "system.cpu_limit_pct", "int", 25, {"min": 5, "max": 100}, "Background workers pause when system CPU is above this"),
    ("System", "system.history_s", "int", 5, {"min": 1, "max": 300}, "Seconds between system samples"),
    ("System", "retention.days", "int", 14, {"min": 1, "max": 3650}, "Days to keep activity, notifications and audit entries"),
    ("System", "retention.shots", "int", 200, {"min": 0, "max": 5000}, "Most screenshot files kept"),
    ("System", "project.scan_minutes", "int", 10, {"min": 1, "max": 1440}, "Minutes between project rescans"),
    ("System", "agents.max_parallel", "int", 2, {"min": 1, "max": 8}, "Most coding agents running at once"),
    ("System", "agents.timeout_min", "int", 45, {"min": 1, "max": 600}, "Stop a coding agent after this many minutes"),
    ("System", "system.autostart", "bool", False, {}, "Start Hukum Desktop when you sign in to Windows"),
    ("System", "system.tray", "bool", True, {}, "Show the Hukum icon in the system tray (open dashboard, emergency stop, quit)"),
    ("System", "agents.codex_model", "str", "", {}, "Model passed to `codex exec -m` (empty = Codex's own default)"),
    ("System", "shell.timeout_s", "int", 120, {"min": 5, "max": 3600}, "Time limit for shell commands"),
    ("Appearance", "ui.accent", "str", "#36B9FF", {}, "Accent colour (hex)"),
    ("Appearance", "ui.font_size", "int", 14, {"min": 11, "max": 20}, "Base font size in pixels"),
    ("Appearance", "ui.motion", "choice", "normal", {"choices": ["off", "reduced", "normal"]}, "Animation intensity"),
]
SPEC = {s[1]: s for s in SETTINGS}
_lock = threading.RLock()
_cache = None
_listeners = []
CFG_PATH = os.path.join(DATA_DIR, "settings.json")
SECRET_PREFIX = "HukumDesktop/" + ("test/" if os.environ.get("HUKUM_DATA") else "")   # test runs never touch the real secrets


def _load():
    global _cache
    if _cache is None:
        try:
            with open(CFG_PATH, encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def on_change(fn):
    _listeners.append(fn)


def get(key):
    spec = SPEC[key]
    if spec[2] == "secret":
        from . import secrets_store
        return secrets_store.read(SECRET_PREFIX + key) or ""
    with _lock:
        v = _load().get(key, spec[3])
    return v


def get_list(key):
    return [x.strip() for x in str(get(key)).split(",") if x.strip()]


def coerce(key, value):
    """Validate and convert a value for a setting; raises ValueError with a readable message."""
    if key not in SPEC:
        raise ValueError(f"unknown setting {key}")
    _, _, kind, default, extra, _d = SPEC[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("1", "true", "on", "yes"):
            return True
        if str(value).lower() in ("0", "false", "off", "no"):
            return False
        raise ValueError(f"{key} must be on or off")
    if kind in ("int", "float"):
        try:
            v = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if "min" in extra and v < extra["min"] or "max" in extra and v > extra["max"]:
            raise ValueError(f"{key} must be between {extra.get('min')} and {extra.get('max')}")
        return v
    if kind == "choice":
        if str(value) not in extra["choices"]:
            raise ValueError(f"{key} must be one of {extra['choices']}")
        return str(value)
    v = str(value).strip()
    if key == "ui.accent" and not (len(v) == 7 and v.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in v[1:])):
        raise ValueError("accent must look like #36B9FF")
    if key.endswith("_url") or key == "gateway.url":
        if v and not v.startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https://")
    return v


def set_(key, value):
    v = coerce(key, value)
    kind = SPEC[key][2]
    if kind == "secret":
        from . import secrets_store
        if v:
            secrets_store.write(SECRET_PREFIX + key, v)
        else:
            secrets_store.delete(SECRET_PREFIX + key)
    else:
        with _lock:
            cfg = _load()
            cfg[key] = v
            tmp = CFG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, CFG_PATH)
    for fn in list(_listeners):
        try:
            fn(key, v)
        except Exception:
            pass
    return v


def describe(include_values=True):
    """For the Settings page. Secrets never leave: only whether one is set."""
    out = []
    for group, key, kind, default, extra, desc in SETTINGS:
        item = {"group": group, "key": key, "kind": kind, "desc": desc, "default": default if kind != "secret" else "",
                "choices": extra.get("choices"), "min": extra.get("min"), "max": extra.get("max")}
        if include_values:
            if kind == "secret":
                item["is_set"] = bool(get(key))
                item["value"] = ""
            else:
                item["value"] = get(key)
        out.append(item)
    return out


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, action TEXT, target TEXT,
  risk TEXT, decision TEXT, detail TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT, risk TEXT, summary TEXT,
  status TEXT DEFAULT 'pending', decided REAL, source TEXT);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, app TEXT, project TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, severity TEXT, title TEXT, body TEXT,
  key TEXT, count INTEGER DEFAULT 1, last_ts REAL, acked INTEGER DEFAULT 0, source TEXT);
CREATE INDEX IF NOT EXISTS notif_key ON notifications(key, last_ts);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, detail TEXT, priority INTEGER DEFAULT 2,
  status TEXT DEFAULT 'todo', due TEXT, project TEXT, agent TEXT, deps TEXT DEFAULT '[]', created REAL, updated REAL, result TEXT);
CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, text TEXT UNIQUE, project TEXT, ts REAL, pinned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS projects(path TEXT PRIMARY KEY, name TEXT, data TEXT, scanned REAL);
CREATE TABLE IF NOT EXISTS workflows(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, spec TEXT, enabled INTEGER DEFAULT 1, created REAL, last_run REAL);
CREATE TABLE IF NOT EXISTS wf_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, wf_id INTEGER, ts REAL, status TEXT, log TEXT);
CREATE TABLE IF NOT EXISTS agent_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, repo TEXT, prompt TEXT, status TEXT DEFAULT 'queued',
  deps TEXT DEFAULT '[]', readonly INTEGER DEFAULT 0, files TEXT DEFAULT '[]', output TEXT DEFAULT '', verify TEXT, verify_result TEXT,
  task_id INTEGER, created REAL, updated REAL, group_id TEXT);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, direction TEXT, contact TEXT, text TEXT, status TEXT, via TEXT);
CREATE TABLE IF NOT EXISTS sysmon(ts REAL PRIMARY KEY, cpu REAL, ram REAL, gpu REAL, disk REAL, net_down REAL, net_up REAL, battery REAL);
CREATE TABLE IF NOT EXISTS shots(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, app TEXT, title TEXT, path TEXT, text_hash TEXT);
CREATE TABLE IF NOT EXISTS conv(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, role TEXT, text TEXT, project TEXT);
"""
_db_lock = threading.RLock()
DB_PATH = os.path.join(DATA_DIR, "hukum.db")


def conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _db_lock, contextlib.closing(conn()) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


def q(sql, args=()):
    with _db_lock, contextlib.closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def x(sql, args=()):
    """Execute a write; returns lastrowid."""
    with _db_lock, contextlib.closing(conn()) as c:
        with c:
            cur = c.execute(sql, args)
        return cur.lastrowid


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def audit(actor, action, target="", risk="low", decision="allowed", detail="", result=""):
    from .redact import redact
    target, detail, result = redact(target), redact(detail), redact(result)
    return x("INSERT INTO audit(ts,actor,action,target,risk,decision,detail,result) VALUES(?,?,?,?,?,?,?,?)",
             (time.time(), actor, action, str(target)[:300], risk, decision, str(detail)[:1500], str(result)[:1500]))


def activity(kind, text, app="", project=""):
    from .redact import redact
    text = redact(text)
    return x("INSERT INTO activity(ts,kind,app,project,text) VALUES(?,?,?,?,?)", (time.time(), kind, app, project, str(text)[:2000]))


def purge():
    """Apply the retention setting."""
    cutoff = time.time() - int(get("retention.days")) * 86400
    for t in ("audit", "activity", "sysmon", "shots"):
        x(f"DELETE FROM {t} WHERE ts<?", (cutoff,))
    x("DELETE FROM notifications WHERE last_ts<?", (cutoff,))
    x("DELETE FROM conv WHERE ts<?", (cutoff,))
