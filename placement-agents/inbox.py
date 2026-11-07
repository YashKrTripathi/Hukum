"""Unified inbox: every message/call notification the phone sees. Tracks what Boss has not dealt with
('open'), reminds him, and lets Hukum read and reply. Status: open -> read (he opened it on the phone)
or handled (he told Hukum / Hukum replied). A swiped-away notification stays open: that's the 'forgot' case."""
import json
import time
from datetime import datetime
import db

APP_NAMES = {"whatsapp": "WhatsApp", "whatsapp_business": "WhatsApp Business", "discord": "Discord",
             "sms": "SMS", "telegram": "Telegram", "call": "Call"}
NUDGE_AFTER_MIN = 30          # first reminder
NUDGE_EVERY_MIN = 60          # then hourly
MAX_NUDGES = 3
QUIET_HOURS = (23, 7)         # no nudges between 23:00 and 07:00


def _init():
    db.init()


def add(app, sender, chat, text, ts, nkey, can_reply):
    """Store one incoming message. Ignores duplicates (same notification key and text)."""
    _init()
    text = (text or "").strip()[:500]
    if not text:
        return None
    ts = ts or time.time()
    dup = db.q("SELECT id FROM inbox WHERE nkey=? AND text=? AND ts>?", (nkey, text, ts - 120))
    if dup:
        return dup[0]["id"]
    db.x("INSERT INTO inbox(app,sender,chat,text,ts,nkey,can_reply) VALUES(?,?,?,?,?,?,?)",
         (app, sender or "?", chat or "", text, ts or time.time(), nkey or "", 1 if can_reply else 0))
    return db.q("SELECT max(id) m FROM inbox")[0]["m"]


def removed(nkey, reason):
    """The phone's notification disappeared. 'read' means he opened it; 'swiped' leaves it open."""
    if nkey and reason == "read":
        db.x("UPDATE inbox SET status='read' WHERE nkey=? AND status='open'", (nkey,))


def _ago(ts):
    m = int((time.time() - ts) / 60)
    if m < 1:
        return "abhi abhi"
    if m < 60:
        return f"{m} min pehle"
    h = m // 60
    return f"{h} ghante pehle" if h < 24 else f"{h // 24} din pehle"


def messages(app=None, sender=None, only_open=True, limit=15):
    _init()
    sql, args = "SELECT * FROM inbox WHERE 1=1", []
    if only_open:
        sql += " AND status='open'"
    if app:
        sql += " AND lower(app)=lower(?)"; args.append(app.replace(" ", "_"))
    if sender:
        sql += " AND lower(sender) LIKE lower(?)"; args.append(f"%{sender}%")
    sql += " ORDER BY ts DESC LIMIT ?"; args.append(int(limit))
    return db.q(sql, tuple(args))


def format_rows(rows):
    out = []
    for r in reversed(rows):
        t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
        out.append(f"M{r['id']} [{APP_NAMES.get(r['app'], r['app'])}] {r['sender']} ({t}, {_ago(r['ts'])}): {r['text']}")
    return "\n".join(out) or "No unread messages."


def mark_handled(sender=None, ids=None):
    _init()
    n = 0
    for i in ids or []:
        db.x("UPDATE inbox SET status='handled' WHERE id=? AND status='open'", (int(str(i).lstrip("Mm")),)); n += 1
    if sender:
        db.x("UPDATE inbox SET status='handled' WHERE lower(sender) LIKE lower(?) AND status='open'", (f"%{sender}%",))
    return "Marked as handled"


def reply_target(sender, app=None):
    """Latest replyable message from this sender (to find the phone notification to answer through)."""
    rows = [r for r in messages(app=app, sender=sender, only_open=False, limit=10) if r["can_reply"]]
    return rows[0] if rows else None


def summary():
    """One short line per sender for the system prompt."""
    rows = messages(limit=100)
    if not rows:
        return "No unanswered messages."
    by = {}
    for r in rows:
        by.setdefault((r["app"], r["sender"]), []).append(r)
    lines = []
    for (app, sender), rs in list(by.items())[:8]:
        lines.append(f"- {sender} ({APP_NAMES.get(app, app)}): {len(rs)} unread, latest {_ago(rs[0]['ts'])}: "
                     f"\"{rs[0]['text'][:80]}\"")
    return "\n".join(lines)


def _quiet():
    h = datetime.now().hour
    a, b = QUIET_HOURS
    return h >= a or h < b


def due_nudges():
    """Texts for senders whose messages have sat unanswered long enough. Marks them nudged."""
    _init()
    if _quiet() or db.get("call_mode", "normal") in ("sleeping", "driving"):
        return []
    now = time.time()
    rows = db.q("SELECT * FROM inbox WHERE status='open' AND nudges<? AND ts<? AND last_nudge<? ORDER BY ts",
                (MAX_NUDGES, now - NUDGE_AFTER_MIN * 60, now - NUDGE_EVERY_MIN * 60))
    if not rows:
        return []
    by = {}
    for r in rows:
        by.setdefault((r["app"], r["sender"]), []).append(r)
    texts = []
    items = list(by.items())
    if len(items) == 1:
        (app, sender), rs = items[0]
        if app == "call":
            texts.append(f"Boss, {sender} ka call aaya tha {_ago(rs[0]['ts'])}. Callback karna hai?")
        else:
            texts.append(f"Boss, {sender} ne {_ago(rs[0]['ts'])} {APP_NAMES.get(app, app)} pe likha tha: "
                         f"\"{rs[-1]['text'][:80]}\". Abhi tak reply nahi gaya. Reply bolu?")
    else:
        names = ", ".join(s for (_, s), _ in items[:3])
        texts.append(f"Boss, {len(rows)} messages ka reply baaki hai: {names}"
                     f"{' aur kuch aur' if len(items) > 3 else ''}. Padh ke sunau?")
    ids = [r["id"] for r in rows]
    db.x(f"UPDATE inbox SET nudges=nudges+1, last_nudge=? WHERE id IN ({','.join('?' * len(ids))})", (now, *ids))
    return texts


def nudge_loop(push, speak=None):
    """Background thread body: every minute, push due reminders to the phone."""
    while True:
        try:
            for t in due_nudges():
                payload = {"text": t, "speech": speak(t) if speak else t}
                push("nudge", json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print("nudge error:", e)
        time.sleep(60)
