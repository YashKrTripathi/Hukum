"""Phone-app channel using ntfy (open source push notifications; Android/iOS app).
Install the ntfy app, subscribe to your secret NTFY_TOPIC. Button taps come back on
<topic>-reply, which the listener thread reads (no inbound server needed).
In the app: set the topic's max-priority channel to 'Override Do Not Disturb'."""
import json
import queue
import threading
import time
import httpx
from config import NTFY_SERVER, NTFY_TOPIC

REPLIES: "queue.Queue[str]" = queue.Queue()


def enabled() -> bool:
    return bool(NTFY_TOPIC)


def push(message, title="Placement Agent", priority=3, buttons=None, tags=None, link=None) -> bool:
    """buttons: list of (label, reply_value). priority 5 = urgent/'call'.
    link: opens the voice page when you tap '🎙 Talk now' (also opens when you tap the notification)."""
    if not enabled():
        return False
    body = {"topic": NTFY_TOPIC, "message": message, "title": title, "priority": priority}
    if tags:
        body["tags"] = tags
    actions = []
    if link:
        body["click"] = link
        actions.append({"action": "view", "label": "🎙 Talk now", "url": link, "clear": True})
    if buttons:
        actions += [{"action": "http", "label": lbl, "method": "POST", "clear": True,
                     "url": f"{NTFY_SERVER}/{NTFY_TOPIC}-reply", "body": val} for lbl, val in buttons]
    if actions:
        body["actions"] = actions[:3]
    try:
        httpx.post(NTFY_SERVER, json=body, timeout=10).raise_for_status()
        return True
    except Exception as e:
        print("ntfy push failed:", e)
        return False


PC_STATE = ("offline", 0.0)   # (state label, unix time) last heartbeat from pc_agent.py


def _listen(suffix, handler):
    url = f"{NTFY_SERVER}/{NTFY_TOPIC}-{suffix}/json"
    while True:
        try:
            with httpx.stream("GET", url, timeout=httpx.Timeout(10, read=None)) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    ev = json.loads(line)
                    if ev.get("event") == "message":
                        handler(ev.get("message", "").strip())
        except Exception as e:
            print(f"ntfy listener [{suffix}] reconnecting:", e)
            time.sleep(5)


def _on_pc(msg):
    global PC_STATE
    PC_STATE = (msg, time.time())


def start_listener(watch_pc=False):
    if not enabled():
        return
    threading.Thread(target=_listen, args=("reply", REPLIES.put), daemon=True).start()
    if watch_pc:
        threading.Thread(target=_listen, args=("pc", _on_pc), daemon=True).start()


def publish_pc(state: str) -> bool:
    """Called by pc_agent.py on your PC: sends only a state label, never window titles."""
    try:
        httpx.post(f"{NTFY_SERVER}/{NTFY_TOPIC}-pc", content=state, timeout=10).raise_for_status()
        return True
    except Exception as e:
        print("heartbeat failed:", e)
        return False
