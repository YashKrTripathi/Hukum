"""Link to the Hukum gateway (the brain server that talks to the phone): phone status, messages through the phone,
alerts to the phone, and the job channel that lets the phone send work to this PC."""
import json
import threading
import time
import urllib.error
import urllib.request

from . import store, events

_state = {"linked": False, "last_poll": 0, "error": ""}
_stop = threading.Event()
_thread = None


def _req(method, path, body=None, key_kind="phone", timeout=20):
    base = store.get("gateway.url").rstrip("/")
    if not base:
        raise RuntimeError("gateway.url is not set")
    key = store.get("gateway.phone_key" if key_kind == "phone" else "gateway.pc_key")
    if not key:
        raise RuntimeError(f"gateway {key_kind} key is not set (Settings > Communication)")
    hdr = {"Content-Type": "application/json", ("X-Key" if key_kind == "phone" else "X-PC-Key"): key}
    r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, hdr, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gateway answered HTTP {e.code}")


def tool(name, args=None, timeout=30):
    """Run one of Hukum's gateway tools (get_messages, reply_message, ...). Returns its text result."""
    return _req("POST", "/api/tool", {"name": name, "args": args or {}}, timeout=timeout).get("result", "")


def status():
    """Phone/gateway health as the dashboard shows it."""
    try:
        r = _req("GET", "/api/status")
        return {"reachable": True, **r}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def phone_notify(text):
    return _req("POST", "/api/notify", {"text": text})


def link_state():
    return dict(_state)


# ---------------------------------------------------------------- job channel (phone -> this PC)
def _job_loop(execute):
    backoff = 3
    while not _stop.is_set():
        if not store.get("gateway.link") or not store.get("gateway.pc_key"):
            _state.update(linked=False, error="")
            _stop.wait(3)
            continue
        try:
            jobs = _req("GET", "/api/pc/poll?wait=20", key_kind="pc", timeout=35).get("jobs", [])
            _state.update(linked=True, last_poll=time.time(), error="")
            backoff = 3
            for j in jobs:
                threading.Thread(target=_run_job, args=(j, execute), daemon=True).start()
        except Exception as e:
            _state.update(linked=False, error=str(e)[:120])
            _stop.wait(backoff)
            backoff = min(backoff * 2, 60)


def _run_job(job, execute):
    jid = job["id"]
    try:
        out = execute(job["kind"], job.get("args") or {}, jid)
        if out is not None:                         # long jobs (code) report their own progress
            _req("POST", "/api/pc/result", {"id": jid, "status": "done", "output": str(out)[-3500:]}, key_kind="pc")
    except Exception as e:
        try:
            _req("POST", "/api/pc/result", {"id": jid, "status": "failed", "output": f"{type(e).__name__}: {e}"}, key_kind="pc")
        except Exception:
            pass


def report(jid, status_, output):
    try:
        _req("POST", "/api/pc/result", {"id": jid, "status": status_, "output": str(output)[-3500:]}, key_kind="pc")
    except Exception:
        pass


def start(execute):
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_job_loop, args=(execute,), daemon=True, name="gateway-link")
    _thread.start()


def stop():
    _stop.set()
