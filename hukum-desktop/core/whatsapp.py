"""WhatsApp through the PHONE (no WhatsApp Web scraping). Two routes:
  - replies to notifications that the Hukum phone app already captured: gateway tools get_messages / reply_message
  - new messages to a number: adb (USB debugging) opens a wa.me deep link with the text filled in, then taps Send
    after a UI dump confirms the Send button is on screen.
Sending is always the `msg.send` action (high risk): the dashboard shows the exact message and recipient first."""
import os
import re
import subprocess
import time
import urllib.parse

from . import store, gateway, events

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _adb(*args, timeout=25):
    path = store.get("adb.path")
    if not path or not os.path.exists(path):
        raise RuntimeError("adb.exe not found (Settings > Communication > adb.path)")
    r = subprocess.run([path, *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


def phone_connected():
    try:
        out = _adb("devices")
        lines = [ln for ln in out.splitlines()[1:] if ln.strip()]
        ok = [ln.split()[0] for ln in lines if ln.endswith("device")]
        return {"connected": bool(ok), "devices": ok, "raw": [ln for ln in lines if not ln.endswith("device")]}
    except Exception as e:
        return {"connected": False, "devices": [], "error": str(e)[:150]}


def inbox(limit=20):
    """Recent messages the phone captured (observed through notifications)."""
    text = gateway.tool("get_messages", {"limit": limit})
    return text


def contacts(query=""):
    """Phone contacts matching the query (adb content provider; needs the phone connected and unlocked)."""
    out = _adb("shell", "content", "query", "--uri", "content://com.android.contacts/data/phones",
               "--projection", "display_name:data1")
    rows = []
    for ln in out.splitlines():
        m = re.search(r"display_name=(.*?), data1=(.*)$", ln)
        if m:
            rows.append({"name": m[1].strip(), "number": re.sub(r"[^\d+]", "", m[2])})
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r["name"].lower() or q in r["number"]]
    seen, uniq = set(), []
    for r in rows:
        if r["number"] not in seen:
            seen.add(r["number"])
            uniq.append(r)
    return uniq[:20]


def draft(contact, text):
    mid = store.x("INSERT INTO messages(ts,direction,contact,text,status,via) VALUES(?,?,?,?,?,?)",
                  (time.time(), "out", contact, text, "draft", "whatsapp"))
    events.emit("message", {"id": mid, "status": "draft"})
    return store.one("SELECT * FROM messages WHERE id=?", (mid,))


def history(limit=40):
    return store.q("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (int(limit),))


def reply(contact, text):
    """Reply to a conversation the phone app has a notification for."""
    r = gateway.tool("reply_message", {"contact": contact, "text": text}, timeout=45)
    _log(contact, text, "sent" if "sent" in r.lower() or "ok" in r.lower() else "unknown", "gateway")
    return r


def _log(contact, text, status, via):
    store.x("INSERT INTO messages(ts,direction,contact,text,status,via) VALUES(?,?,?,?,?,?)", (time.time(), "out", contact, text, status, via))


def send_new(number, text, press_send=True):
    """Open a chat with `number` with the text filled in and (optionally) tap Send. Verifies the Send button before tapping."""
    num = re.sub(r"[^\d]", "", number)
    if len(num) < 8:
        raise ValueError("a full phone number with country code is needed (e.g. 919876543210)")
    if not phone_connected()["connected"]:
        raise RuntimeError("phone not connected over adb (USB debugging, screen unlocked)")
    url = f"https://wa.me/{num}?text={urllib.parse.quote(text)}"
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url.replace("&", "\\&"), "com.whatsapp")
    time.sleep(4)
    if not press_send:
        _log(num, text, "opened", "adb")
        return "chat opened with the message filled in; not sent"
    _adb("shell", "uiautomator", "dump", "/sdcard/hk_ui.xml")
    xml = _adb("shell", "cat", "/sdcard/hk_ui.xml")
    m = re.search(r'content-desc="Send"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml) or \
        re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*content-desc="Send"', xml)
    if not m:
        _log(num, text, "failed", "adb")
        raise RuntimeError("could not find the Send button on the phone screen; nothing was sent")
    x1, y1, x2, y2 = map(int, m.groups())
    _adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    _log(num, text, "sent", "adb")
    return f"sent to {num}"
