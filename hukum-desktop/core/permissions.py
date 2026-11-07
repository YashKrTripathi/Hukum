"""Central permission manager: every action Hukum takes goes through run().

  1. emergency stop blocks everything except harmless reads
  2. the category switch in Settings (perm.*) must be on
  3. the risk level decides whether Boss is asked: low = auto, medium = setting, high = always, critical = always
     (critical needs the exact word CONFIRM typed in the approval box)
  4. the outcome is written to the audit log (with secrets redacted)
"""
import re
import threading
import time
import json
from . import store, events
from .redact import redact

RISKS = ["low", "medium", "high", "critical"]

# action -> (risk, permission switch)
ACTIONS = {
    "app.list": ("low", "perm.apps"), "app.launch": ("low", "perm.apps"), "app.focus": ("low", "perm.apps"),
    "app.window": ("medium", "perm.apps"), "app.close": ("high", "perm.apps"),
    "ui.read": ("low", "perm.screen"), "ui.find": ("low", "perm.screen"),
    "ui.type": ("medium", "perm.keyboard"), "ui.keys": ("medium", "perm.keyboard"),
    "ui.click": ("medium", "perm.mouse"), "ui.invoke": ("medium", "perm.mouse"),
    "screen.capture": ("low", "perm.screen"), "screen.ocr": ("low", "perm.screen"),
    "file.read": ("low", "perm.files"), "file.write": ("medium", "perm.files"), "file.move": ("medium", "perm.files"),
    "file.delete": ("high", "perm.files"),
    "shell.run": ("medium", "perm.terminal"),
    "agent.run": ("medium", "perm.terminal"), "agent.control": ("low", "perm.terminal"),
    "msg.read": ("low", "perm.messages"), "msg.draft": ("low", "perm.messages"), "msg.send": ("high", "perm.messages"),
    "web.open": ("low", "perm.apps"), "web.submit": ("high", "perm.apps"),
    "system.read": ("low", None), "system.kill": ("high", "perm.apps"),
    "monitor.control": ("low", "perm.monitoring"),
    "memory.write": ("low", None), "task.write": ("low", None), "notify": ("low", None),
    "deploy.prod": ("critical", "perm.terminal"), "payment": ("critical", None), "account.change": ("critical", None),
}

_CRIT = [r"rm\s+-rf\s+/(\s|$)", r"\bformat\s+[a-z]:", r"\bdiskpart\b", r"drop\s+(database|table)", r"terraform\s+destroy",
         r"kubectl\s+delete", r"aws\s+\S+\s+(delete|terminate)", r"\bmkfs\b", r"\bcipher\s+/w", r"reg\s+delete\s+hk"]
_HIGH = [r"\brm\b", r"\bdel\b", r"\brmdir\b", r"\brd\b", r"Remove-Item", r"git\s+push\s+.*(--force|-f\b)", r"git\s+reset\s+--hard",
         r"git\s+clean", r"npm\s+publish", r"docker\s+(rm|rmi|system\s+prune|volume\s+rm)", r"\bshutdown\b", r"\brestart-computer\b",
         r"\breg\s+(add|delete)", r"taskkill", r"\bkill\b", r"Stop-Process", r"pm2\s+(delete|kill)", r"\bssh\b", r"\bscp\b",
         r"deploy", r"\bnet\s+user\b", r"schtasks", r"sc\s+(delete|stop)", r"Set-ExecutionPolicy", r"\bchmod\b", r"\bchown\b",
         r"\bcurl\b.*\|\s*(sh|bash)", r"iwr .*\|\s*iex", r"\btruncate\b", r">\s*/dev/sd"]
_MED = [r"\bnpm\s+(i|install|run|test|ci|build)", r"\byarn\b", r"\bpnpm\b", r"pip\s+install", r"\bgit\s+(add|commit|checkout|switch|merge|pull|push|stash|rebase|clone)",
        r"\bpython\b", r"\bnode\b", r"\bgradle", r"\bmvn\b", r"\bmake\b", r"\bdocker\b", r"\bpm2\b", r"\bcargo\b", r"\bgo\s+(build|run|test)\b",
        r"\bmkdir\b", r"\bcopy\b", r"\bmove\b", r"\bren\b", r"\btouch\b", r"\bmv\b", r"\bcp\b", r">>?\s*\S"]
_LOW = [r"^\s*(dir|ls|cat|type|more|head|tail|echo|whoami|hostname|pwd|cd|where|which|ver|date|time|tree|findstr|grep|rg|sort|wc)\b",
        r"^\s*git\s+(status|log|diff|branch|remote|show|rev-parse|describe|ls-files|config\s+--get)\b",
        r"^\s*(tasklist|netstat|ipconfig|systeminfo|nvidia-smi|ping|nslookup|Get-[A-Za-z]+)\b",
        r"^\s*(python|node|npm|git|java|docker|pip)\s+(--version|-v|-V|version)\b"]


def classify_shell(cmd):
    c = str(cmd or "")
    if any(re.search(p, c, re.I) for p in _CRIT):
        return "critical"
    if any(re.search(p, c, re.I) for p in _HIGH):
        return "high"
    # a command chain is as risky as its riskiest part
    parts = [p for p in re.split(r"&&|\|\||;|\|", c) if p.strip()]
    worst = "low"
    for p in parts or [c]:
        if any(re.search(x, p, re.I) for x in _MED) and not any(re.search(x, p, re.I) for x in _LOW):
            r = "medium"
        elif any(re.search(x, p, re.I) for x in _LOW):
            r = "low"
        else:
            r = "medium"
        if RISKS.index(r) > RISKS.index(worst):
            worst = r
    return worst


def risk_of(action, params=None):
    base = ACTIONS.get(action, ("medium", None))[0]
    if action == "shell.run":
        return classify_shell((params or {}).get("command", ""))
    if action == "agent.run" and (params or {}).get("readonly"):
        return "low"
    return base


class Denied(Exception):
    pass


# ---------------------------------------------------------------- emergency stop
_estop = {"on": False, "reason": "", "ts": 0.0}
_stop_hooks = []
_waiters = {}            # approval id -> Event
_lock = threading.RLock()


def on_estop(fn):
    _stop_hooks.append(fn)


def estop_state():
    return dict(_estop)


def estop(reason="manual"):
    with _lock:
        _estop.update(on=True, reason=reason, ts=time.time())
        pend = store.q("SELECT id FROM approvals WHERE status='pending'")
    for p in pend:
        _decide(p["id"], "rejected")
    for fn in list(_stop_hooks):
        try:
            fn()
        except Exception:
            pass
    store.audit("system", "emergency_stop", reason, "critical", "stopped")
    events.emit("estop", {"on": True, "reason": reason})


def release():
    _estop.update(on=False, reason="", ts=0.0)
    store.audit("user", "emergency_stop_released", "", "low", "ok")
    events.emit("estop", {"on": False})


# ---------------------------------------------------------------- approvals
def _decide(aid, status):
    store.x("UPDATE approvals SET status=?, decided=? WHERE id=? AND status='pending'", (status, time.time(), aid))
    ev = _waiters.get(aid)
    if ev:
        ev.set()
    events.emit("approval", {"id": aid, "status": status})


def pending():
    rows = store.q("SELECT * FROM approvals WHERE status='pending' ORDER BY id")
    for r in rows:
        r["action"] = json.loads(r["action"])
    return rows


def approve(aid, typed=""):
    row = store.one("SELECT * FROM approvals WHERE id=?", (aid,))
    if not row or row["status"] != "pending":
        return False
    if row["risk"] == "critical" and typed.strip() != "CONFIRM":
        raise Denied("Critical actions need the word CONFIRM typed in the box")
    if _estop["on"]:
        raise Denied("Emergency stop is on")
    _decide(aid, "approved")
    store.audit("user", "approve", f"approval {aid}", row["risk"], "approved", row["summary"])
    return True


def reject(aid):
    row = store.one("SELECT * FROM approvals WHERE id=?", (aid,))
    if not row or row["status"] != "pending":
        return False
    _decide(aid, "rejected")
    store.audit("user", "reject", f"approval {aid}", row["risk"], "rejected", row["summary"])
    return True


def _wait_for_approval(action, params, risk, summary, source):
    aid = store.x("INSERT INTO approvals(ts,action,risk,summary,status,source) VALUES(?,?,?,?, 'pending', ?)",
                  (time.time(), json.dumps({"action": action, "params": _safe_params(params)}), risk, summary, source))
    ev = threading.Event()
    _waiters[aid] = ev
    events.emit("approval", {"id": aid, "status": "pending", "risk": risk, "summary": summary})
    timeout = int(store.get("approval.timeout_s"))
    end = time.time() + timeout
    try:
        while time.time() < end:
            if ev.wait(1.0):
                break
            if _estop["on"]:
                _decide(aid, "rejected")
                break
        row = store.one("SELECT status FROM approvals WHERE id=?", (aid,))
        if row["status"] == "pending":
            _decide(aid, "expired")
            return "expired"
        return row["status"]
    finally:
        _waiters.pop(aid, None)


def _safe_params(params):
    out = {}
    for k, v in (params or {}).items():
        s = v if isinstance(v, (int, float, bool)) or v is None else redact(str(v))
        out[k] = s if not isinstance(s, str) else s[:600]
    return out


def decision(action, params=None, preapproved=False):
    """(verdict, risk, reason): verdict is allow | ask | deny. No side effects."""
    risk = risk_of(action, params)
    cfg = ACTIONS.get(action, ("medium", None))
    if _estop["on"] and not (risk == "low" and action in ("system.read", "app.list", "memory.write", "task.write")):
        return "deny", risk, "Emergency stop is on"
    sw = cfg[1]
    if sw and not store.get(sw):
        return "deny", risk, f"'{sw}' is switched off in Settings"
    if action == "msg.send" and store.get("msg.paused"):
        return "deny", risk, "Outgoing messages are paused"
    if risk == "critical":
        return "ask", risk, "critical action"
    if preapproved and risk in ("low", "medium", "high"):
        return "allow", risk, "approved by Boss when he asked"
    if risk == "low":
        return ("allow" if store.get("confirm.low") == "auto" else "ask"), risk, ""
    if risk == "medium":
        return ("allow" if store.get("confirm.medium") == "auto" else "ask"), risk, ""
    if action == "msg.send" and not store.get("msg.confirm"):
        to = str((params or {}).get("contact", "")).lower()
        if to and to in [t.lower() for t in store.get_list("msg.trusted")]:
            return "allow", risk, "trusted contact"
    return "ask", risk, "high-risk action"


def run(actor, action, params, fn, summary=None, preapproved=False, source="local"):
    """Gate and execute fn(). Returns fn's result; raises Denied if refused/rejected."""
    verdict, risk, reason = decision(action, params, preapproved)
    summ = summary or f"{action} {json.dumps(_safe_params(params), ensure_ascii=False)[:200]}"
    if verdict == "deny":
        store.audit(actor, action, summ, risk, "denied", reason)
        raise Denied(reason)
    if verdict == "ask":
        status = _wait_for_approval(action, params, risk, summ, source)
        if status != "approved":
            store.audit(actor, action, summ, risk, status, "not approved")
            raise Denied(f"Not approved ({status})")
    try:
        result = fn()
    except Exception as e:
        store.audit(actor, action, summ, risk, "failed", repr(e)[:300])
        raise
    store.audit(actor, action, summ, risk, "allowed", "", str(result)[:300] if result is not None else "")
    return result
