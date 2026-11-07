"""In-process event bus + ring buffer. The dashboard streams it (Server-Sent Events); workers and the automation
engine subscribe to it."""
import threading
import time

_lock = threading.Condition()
_ring = []
_next = 1
_subs = []


def emit(kind, data=None):
    global _next
    ev = {"id": 0, "ts": time.time(), "type": kind, "data": data or {}}
    with _lock:
        ev["id"] = _next
        _next += 1
        _ring.append(ev)
        del _ring[:-300]
        _lock.notify_all()
    for fn in list(_subs):
        try:
            fn(ev)
        except Exception:
            pass
    return ev


def subscribe(fn):
    _subs.append(fn)


def since(last_id, wait=20.0):
    """Events newer than last_id; blocks up to `wait` seconds when there are none."""
    end = time.time() + wait
    with _lock:
        while True:
            out = [e for e in _ring if e["id"] > last_id]
            if out or time.time() >= end:
                return out
            _lock.wait(min(end - time.time(), 5))


def latest_id():
    with _lock:
        return _next - 1
