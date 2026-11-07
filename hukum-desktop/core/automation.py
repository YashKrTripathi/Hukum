"""Automation engine: user-defined workflows. A workflow = trigger + conditions + steps (tool calls). Triggers: schedule
(daily time, optional weekdays), interval (every N minutes), event (a notification whose title matches text), app
(an app starts or stops). Steps go through the same permission manager as everything else, so a workflow can never do
more than Boss allows; steps that need approval wait for it. Every run is logged with each step's outcome."""
import json
import re
import threading
import time

from . import store, events, tools, notify, apps, permissions

_stop = threading.Event()
_thread = None
_fired = {}            # workflow id -> last trigger key (avoid double fire in the same minute)
_app_state = {}
_running = set()


def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError("a workflow is a JSON object")
    trig = spec.get("trigger") or {}
    t = trig.get("type")
    if t == "schedule":
        if not re.fullmatch(r"\d\d:\d\d", str(trig.get("at", ""))):
            raise ValueError("schedule trigger needs 'at' like 09:30")
    elif t == "interval":
        if int(trig.get("minutes", 0)) < 1:
            raise ValueError("interval trigger needs 'minutes' >= 1")
    elif t == "event":
        if not trig.get("match"):
            raise ValueError("event trigger needs 'match' text")
    elif t == "app":
        if not trig.get("app") or trig.get("on") not in ("start", "stop"):
            raise ValueError("app trigger needs 'app' and on=start|stop")
    elif t != "manual":
        raise ValueError("trigger type must be schedule, interval, event, app or manual")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("a workflow needs at least one step")
    for s in steps:
        if s.get("tool") not in tools.TOOLS and s.get("tool") != "briefing":
            raise ValueError(f"unknown tool '{s.get('tool')}'")
    return spec


def save(name, spec, enabled=True):
    validate(spec)
    now = time.time()
    store.x("INSERT INTO workflows(name,spec,enabled,created) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET spec=excluded.spec, enabled=excluded.enabled",
            (name, json.dumps(spec), int(enabled), now))
    return get(name)


def get(name_or_id):
    r = store.one("SELECT * FROM workflows WHERE id=? OR name=?", (name_or_id if str(name_or_id).isdigit() else -1, str(name_or_id)))
    if r:
        r["spec"] = json.loads(r["spec"])
    return r


def list_all():
    rows = store.q("SELECT * FROM workflows ORDER BY name")
    for r in rows:
        r["spec"] = json.loads(r["spec"])
        last = store.one("SELECT status,ts FROM wf_runs WHERE wf_id=? ORDER BY id DESC LIMIT 1", (r["id"],))
        r["last"] = last
    return rows


def set_enabled(wid, on):
    store.x("UPDATE workflows SET enabled=? WHERE id=?", (int(on), int(wid)))


def delete(wid):
    store.x("DELETE FROM workflows WHERE id=?", (int(wid),))
    store.x("DELETE FROM wf_runs WHERE wf_id=?", (int(wid),))


def runs(wid=None, limit=30):
    if wid:
        return store.q("SELECT * FROM wf_runs WHERE wf_id=? ORDER BY id DESC LIMIT ?", (int(wid), limit))
    return store.q("SELECT r.*, w.name FROM wf_runs r LEFT JOIN workflows w ON w.id=r.wf_id ORDER BY r.id DESC LIMIT ?", (limit,))


def _conditions_ok(conds):
    for c in conds or []:
        t = c.get("type")
        if t == "time_between":
            now = time.strftime("%H:%M")
            a, b = c["from"], c["to"]
            if not ((a <= now <= b) if a <= b else (now >= a or now <= b)):
                return False, f"outside {a}-{b}"
        elif t == "app_running":
            st = apps.status()
            if not any(s["running"] and c["app"].lower() in (s["id"], s["name"].lower()) for s in st):
                return False, f"{c['app']} not running"
        elif t == "weekday":
            if time.strftime("%a").lower()[:3] not in [d.lower()[:3] for d in c["days"]]:
                return False, "not on a selected weekday"
    return True, ""


def run(wf, reason="manual"):
    """Execute a workflow now. Returns {status, log}."""
    if wf["id"] in _running:
        return {"status": "skipped", "log": "already running"}
    _running.add(wf["id"])
    log, status = [], "ok"
    try:
        spec = wf["spec"]
        ok, why = _conditions_ok(spec.get("conditions"))
        if not ok and reason != "manual":
            return {"status": "skipped", "log": f"condition not met: {why}"}
        for i, s in enumerate(spec["steps"], 1):
            tries = 1 + int(spec.get("retry", 0))
            for a in range(tries):
                if s["tool"] == "briefing":
                    from . import commander
                    res = {"ok": True, "result": commander.briefing()}
                else:
                    res = tools.call(s["tool"], s.get("args") or {}, actor=f"workflow:{wf['name']}", source="workflow")
                if res["ok"]:
                    break
                time.sleep(2)
            log.append(f"{i}. {s['tool']}: " + ("ok" if res["ok"] else f"FAILED - {res['error']}"))
            if not res["ok"]:
                status = "failed"
                break
        if spec.get("notify"):
            notify.notify("info" if status == "ok" else "warning", f"Workflow '{wf['name']}' {status}", "; ".join(log)[:400],
                          key=f"wf:{wf['id']}", source="automation", force=True)
    except Exception as e:
        status = "failed"
        log.append(f"error: {e}")
    finally:
        _running.discard(wf["id"])
    store.x("INSERT INTO wf_runs(wf_id,ts,status,log) VALUES(?,?,?,?)", (wf["id"], time.time(), status, "\n".join(log)))
    store.x("UPDATE workflows SET last_run=? WHERE id=?", (time.time(), wf["id"]))
    events.emit("workflow", {"id": wf["id"], "status": status})
    return {"status": status, "log": "\n".join(log)}


def run_async(wf, reason):
    threading.Thread(target=run, args=(wf, reason), daemon=True, name=f"wf-{wf['id']}").start()


def _on_event(ev):
    if ev.get("type") != "notification":
        return
    title = (ev.get("data") or {}).get("title", "")
    for wf in list_all():
        t = wf["spec"].get("trigger", {})
        if wf["enabled"] and t.get("type") == "event" and t["match"].lower() in title.lower():
            run_async(wf, "event")


def _tick():
    now = time.time()
    hm, wd = time.strftime("%H:%M"), time.strftime("%a").lower()[:3]
    cur_apps = None
    for wf in list_all():
        if not wf["enabled"]:
            continue
        t = wf["spec"].get("trigger", {})
        key = None
        if t["type"] == "schedule" and t["at"] == hm and (not t.get("days") or wd in [d.lower()[:3] for d in t["days"]]):
            key = time.strftime("%Y%m%d%H%M")
        elif t["type"] == "interval" and now - (wf["last_run"] or wf["created"]) >= int(t["minutes"]) * 60:
            key = str(int(now // 60))
        elif t["type"] == "app":
            if cur_apps is None:
                cur_apps = {s["id"]: s["running"] for s in apps.status()}
            aid = (apps.resolve(t["app"]) or {}).get("id", t["app"].lower())
            was, is_ = _app_state.get(aid), cur_apps.get(aid, False)
            _app_state[aid] = is_
            if was is not None and ((t["on"] == "start" and is_ and not was) or (t["on"] == "stop" and was and not is_)):
                key = str(int(now))
        if key and _fired.get(wf["id"]) != key:
            _fired[wf["id"]] = key
            run_async(wf, t["type"])


def _loop():
    while not _stop.is_set():
        try:
            if not permissions.estop_state()["on"]:
                _tick()
        except Exception:
            pass
        _stop.wait(20)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    events.subscribe(_on_event)
    _thread = threading.Thread(target=_loop, daemon=True, name="automation")
    _thread.start()


def stop():
    _stop.set()


def templates():
    return [
        {"name": "Morning briefing", "spec": {"trigger": {"type": "schedule", "at": "09:00"}, "steps": [{"tool": "briefing", "args": {}}], "notify": True}},
        {"name": "Start dev workspace", "spec": {"trigger": {"type": "manual"}, "steps": [{"tool": "app_launch", "args": {"name": "vscode"}}, {"tool": "app_launch", "args": {"name": "chrome"}}]}},
        {"name": "Disk and RAM check", "spec": {"trigger": {"type": "interval", "minutes": 60}, "steps": [{"tool": "system_status", "args": {}}], "notify": False}},
        {"name": "Tell me about failed builds", "spec": {"trigger": {"type": "event", "match": "build failed"}, "steps": [{"tool": "notify", "args": {"title": "Build failed - check the terminal", "severity": "warning"}}]}},
    ]
