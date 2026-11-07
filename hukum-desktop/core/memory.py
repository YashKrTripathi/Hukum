"""Persistent memory (facts, preferences, decisions, objectives) and the task manager."""
import json
import re
import time

from . import store, events


# ---------------------------------------------------------------- memory
def remember(text, kind="fact", project="", pinned=False):
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        raise ValueError("nothing to remember")
    if kind not in ("fact", "pref", "decision", "objective", "workflow"):
        kind = "fact"
    if re.search(r"(?i)\b(pass(word|code)?|pwd|pin|otp|cvv)\b\s*(is|=|:|hai|है)?\s*\S+|पासवर्ड", text):
        raise ValueError("Passwords, PINs and OTPs are never saved in memory (it is plain text and can reach AI prompts). Save it in the phone app: More > Passwords.")
    from .redact import redact
    text = redact(text)[:500]
    store.x("INSERT OR IGNORE INTO memory(kind,text,project,ts,pinned) VALUES(?,?,?,?,?)", (kind, text, project, time.time(), int(pinned)))
    events.emit("memory", {"text": text})
    return store.one("SELECT * FROM memory WHERE text=?", (text,))


def forget(mid):
    store.x("DELETE FROM memory WHERE id=?", (int(mid),))


def pin(mid, on=True):
    store.x("UPDATE memory SET pinned=? WHERE id=?", (int(on), int(mid)))


def recall(query="", kind=None, limit=30):
    rows = store.q("SELECT * FROM memory ORDER BY pinned DESC, ts DESC LIMIT 400")
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if query:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        scored = []
        for r in rows:
            t = r["text"].lower()
            sc = sum(1 for w in words if w in t)
            if sc:
                scored.append((sc, r))
        rows = [r for _, r in sorted(scored, key=lambda x: -x[0])]
    return rows[:limit]


def context_block(limit=12):
    rows = recall(limit=limit)
    return "\n".join(f"- ({r['kind']}) {r['text']}" for r in rows) or "(nothing remembered yet)"


# ---------------------------------------------------------------- tasks
STATUSES = ("todo", "doing", "done", "cancelled")


def add_task(title, detail="", priority=2, due="", project="", agent="", deps=None):
    title = str(title).strip()
    if not title:
        raise ValueError("a task needs a title")
    if due:
        time.strptime(due, "%Y-%m-%d")
    now = time.time()
    tid = store.x("INSERT INTO tasks(title,detail,priority,status,due,project,agent,deps,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (title[:200], detail[:2000], int(priority), "todo", due, project, agent, json.dumps(deps or []), now, now))
    events.emit("task", {"id": tid})
    return get_task(tid)


def get_task(tid):
    r = store.one("SELECT * FROM tasks WHERE id=?", (int(tid),))
    if r:
        r["deps"] = json.loads(r["deps"] or "[]")
    return r


def update_task(tid, **f):
    allowed = {"title", "detail", "priority", "status", "due", "project", "agent", "result"}
    sets, args = [], []
    for k, v in f.items():
        if k not in allowed:
            continue
        if k == "status" and v not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if k == "due" and v:
            time.strptime(v, "%Y-%m-%d")
        sets.append(f"{k}=?")
        args.append(v)
    if "deps" in f:
        sets.append("deps=?")
        args.append(json.dumps(f["deps"]))
    if not sets:
        return get_task(tid)
    sets.append("updated=?")
    args += [time.time(), int(tid)]
    store.x(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", args)
    events.emit("task", {"id": int(tid)})
    return get_task(tid)


def delete_task(tid):
    store.x("DELETE FROM tasks WHERE id=?", (int(tid),))


def list_tasks(status=None, project=None, open_only=False):
    rows = store.q("SELECT * FROM tasks ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, priority, due, id")
    out = []
    for r in rows:
        r["deps"] = json.loads(r["deps"] or "[]")
        if status and r["status"] != status:
            continue
        if open_only and r["status"] in ("done", "cancelled"):
            continue
        if project and r["project"] != project:
            continue
        r["overdue"] = bool(r["due"] and r["status"] in ("todo", "doing") and r["due"] < time.strftime("%Y-%m-%d"))
        r["blocked"] = any((get_task(d) or {}).get("status") not in ("done",) for d in r["deps"])
        out.append(r)
    return out


def overdue():
    return [t for t in list_tasks(open_only=True) if t["overdue"]]
