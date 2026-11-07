"""Notification service: severity levels, grouping of repeated alerts, Windows tray toasts, dashboard events,
optional spoken alerts and phone push through the Hukum gateway."""
import base64
import subprocess
import threading
import time

from . import store, events
from .redact import redact

LEVELS = {"info": 0, "warning": 1, "error": 2}


def notify(severity, title, body="", key=None, source="hukum", force=False):
    """Record (and maybe raise) a notification. Same key within the cooldown is grouped into one entry with a count."""
    severity = severity if severity in LEVELS else "info"
    title, body = redact(title)[:160], redact(body)[:600]
    key = key or f"{source}:{title}"
    now = time.time()
    cooldown = int(store.get("notify.cooldown_s"))
    prev = store.one("SELECT * FROM notifications WHERE key=? AND last_ts>? ORDER BY id DESC LIMIT 1", (key, now - cooldown))
    if prev and not force:
        store.x("UPDATE notifications SET count=count+1, last_ts=?, body=? WHERE id=?", (now, body or prev["body"], prev["id"]))
        events.emit("notification_update", {"id": prev["id"], "count": prev["count"] + 1})
        return {"id": prev["id"], "grouped": True}
    raise_it = LEVELS[severity] >= LEVELS.get(store.get("monitor.alert_min_severity"), 1) or force
    nid = store.x("INSERT INTO notifications(ts,severity,title,body,key,count,last_ts,acked,source) VALUES(?,?,?,?,?,?,?,?,?)",
                  (now, severity, title, body, key, 1, now, 0 if raise_it else 1, source))
    item = {"id": nid, "severity": severity, "title": title, "body": body, "source": source, "ts": now, "raised": raise_it}
    events.emit("notification", item)
    if raise_it:
        if store.get("notify.toast"):
            threading.Thread(target=_toast, args=(title, body, severity), daemon=True).start()
        if store.get("notify.phone") and LEVELS[severity] >= 1:
            threading.Thread(target=_phone, args=(f"{title}. {body}"[:300],), daemon=True).start()
    return item


def _toast(title, body, severity):
    ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
          "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
          "$n.ShowBalloonTip(6000,'%s','%s','%s');Start-Sleep 7;$n.Dispose()" % (
              title.replace("'", "''")[:60], (body or title).replace("'", "''")[:200].replace("\n", " "),
              {"error": "Error", "warning": "Warning"}.get(severity, "Info")))
    try:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand",
                          base64.b64encode(ps.encode("utf-16-le")).decode()], creationflags=0x08000000,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _phone(text):
    try:
        from . import gateway
        gateway.phone_notify(text)
    except Exception:
        pass


def ack(nid):
    store.x("UPDATE notifications SET acked=1 WHERE id=?", (int(nid),))


def ack_all():
    store.x("UPDATE notifications SET acked=1 WHERE acked=0")


def recent(limit=60, unacked=False):
    sql = "SELECT * FROM notifications " + ("WHERE acked=0 " if unacked else "") + "ORDER BY last_ts DESC LIMIT ?"
    return store.q(sql, (int(limit),))


def counts():
    r = store.q("SELECT severity, COUNT(*) n FROM notifications WHERE acked=0 GROUP BY severity")
    return {x["severity"]: x["n"] for x in r}
