"""Gateway side of the PC body (Phase 5): a job queue between Hukum's brain and the agent on Boss's PC.

Flow:  Hukum tool (pc_run / code_task ...) -> submit() -> PC agent long-polls /api/pc/poll -> runs it ->
       POST /api/pc/result (progress or final) -> the tool returns the output, or the phone gets a nudge when a
       long coding task finishes.
The PC key is separate from the phone key: a leaked PC key can fetch jobs and post results, nothing else.
Jobs live in memory (and are mirrored to the db so 'what is running' survives a gateway restart)."""
import json
import secrets
import threading
import time
import db

_jobs: dict = {}
_order: list = []
_next = 1
_cv = threading.Condition()
_last_poll = 0.0
_push = None          # webserver.push_event, set by webserver at startup

LONG_KINDS = {"code"}


def set_push(fn):
    global _push
    _push = fn


def pc_key() -> str:
    k = db.get("pc_key")
    if not k:
        k = secrets.token_urlsafe(24)
        db.put("pc_key", k)
    return k


def online() -> bool:
    return time.time() - _last_poll < 60


def _save():
    try:
        db.put("pc_jobs", json.dumps([_jobs[i] for i in _order[-30:] if _jobs[i]["kind"] != "api"], ensure_ascii=False))
    except Exception:
        pass


def _load():
    global _next
    try:
        for j in json.loads(db.get("pc_jobs", "[]")):
            if j["status"] in ("queued", "sent", "running"):
                j["status"] = "lost"
                j["output"] = (j.get("output") or "") + "\n(gateway restarted; result lost)"
            _jobs[j["id"]] = j
            _order.append(j["id"])
            _next = max(_next, int(j["id"][1:]) + 1)
    except Exception:
        pass


def submit(kind: str, args: dict) -> dict:
    global _next
    with _cv:
        jid = f"J{_next}"
        _next += 1
        job = {"id": jid, "kind": kind, "args": args, "status": "queued", "output": "",
               "created": time.time(), "updated": time.time()}
        _jobs[jid] = job
        _order.append(jid)
        del _order[:-60]
        for old in [k for k in _jobs if k not in _order]:
            del _jobs[old]
        _save()
        _cv.notify_all()
        return job


def wait_for(jid: str, seconds: float) -> dict:
    """Block until the job leaves queued/sent/running or the time is up."""
    end = time.time() + seconds
    with _cv:
        while _jobs[jid]["status"] in ("queued", "sent", "running"):
            left = end - time.time()
            if left <= 0:
                break
            _cv.wait(min(left, 1.0))
        return dict(_jobs[jid])


def discard(jid: str):
    """Forget a finished relay job (their results can be large and are not worth keeping)."""
    with _cv:
        _jobs.pop(jid, None)
        if jid in _order:
            _order.remove(jid)


def poll(wait: float = 25.0) -> list:
    """Called by the PC agent: returns queued jobs (marking them sent)."""
    global _last_poll
    end = time.time() + wait
    with _cv:
        while True:
            _last_poll = time.time()
            ready = [_jobs[i] for i in _order if _jobs[i]["status"] == "queued"]
            if ready or time.time() >= end:
                break
            _cv.wait(min(end - time.time(), 5.0))
        out = []
        for j in ready:
            j["status"] = "sent"
            j["updated"] = time.time()
            out.append({"id": j["id"], "kind": j["kind"], "args": j["args"]})
        if out:
            _save()
        return out


def result(jid: str, status: str, output: str):
    """Called by the PC agent. status: running (progress) | done | failed | stopped."""
    with _cv:
        j = _jobs.get(jid)
        if not j or j["status"] in ("done", "failed", "stopped"):
            return False
        j["status"] = status if status in ("running", "done", "failed", "stopped") else "failed"
        j["output"] = str(output)[-(400000 if j["kind"] == "api" else 6000):]
        j["updated"] = time.time()
        _save()
        _cv.notify_all()
        finished = j["status"] in ("done", "failed", "stopped")
        kind, args = j["kind"], j["args"]
    if finished and kind in LONG_KINDS and _push:
        tail = j["output"].strip().splitlines()[-4:]
        label = args.get("repo", "")
        _push("nudge", f"Coding task {jid} ({label}) {j['status']}. " + " ".join(tail)[:300])
    return True


def stop(jid: str) -> str:
    with _cv:
        j = _jobs.get(jid)
        if not j:
            return "No such job"
        if j["status"] in ("done", "failed", "stopped"):
            return f"{jid} already {j['status']}"
    submit("stop", {"job": jid})
    return f"Stop requested for {jid}"


# ---- text for the brain ----
def describe(j: dict, tail: int = 1500) -> str:
    a = j["args"]
    what = a.get("command") or a.get("prompt") or a.get("path") or a.get("target") or ""
    head = f"{j['id']} [{j['kind']}] {j['status']}" + (f" - {str(what)[:80]}" if what else "")
    out = (j.get("output") or "").strip()
    return head + (("\n" + out[-tail:]) if out else "")


def status_text() -> str:
    lines = [f"PC is {'ONLINE' if online() else 'OFFLINE (agent not running or PC off)'}"]
    recent = [_jobs[i] for i in _order[-8:]]
    for j in reversed(recent):
        lines.append(describe(j, tail=200).replace("\n", " | "))
    return "\n".join(lines)


def run(kind: str, args: dict, wait: float = 25.0) -> str:
    """Submit and wait; used by synchronous tools. Long jobs return an id to check later."""
    if not online():
        return "PC is offline (the Hukum PC agent is not running). Ask Boss to start it."
    job = submit(kind, args)
    done = wait_for(job["id"], wait)
    if done["status"] in ("queued", "sent"):
        return f"PC did not pick up {job['id']} yet; it will run when the agent responds."
    if done["status"] == "running":
        return f"{job['id']} is still running; ask pc_status or code_status later."
    return describe(done, tail=3000)


_load()
