"""Idle-watcher agent (Windows). Samples the foreground window + keyboard/mouse idle time.
Study windows (IDE, LeetCode, Udemy...) are auto-logged as study minutes.
Distraction windows (YouTube, Instagram, games...) or long idle are flagged."""
import ctypes
import re

STUDY = re.compile(r"intellij|eclipse|visual studio code|vs code|leetcode|udemy|takeuforward|"
                   r"striver|neetcode|geeksforgeeks|javatpoint|baeldung|oracle.*java|notepad\+\+|netbeans", re.I)
DISTRACT = re.compile(r"youtube|instagram|facebook|netflix|hotstar|prime video|twitter|x\.com|reddit|"
                      r"steam|valorant|bgmi|minecraft|spotify|whatsapp|discord|9gag|moj|shorts", re.I)

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None


class _LII(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    if not user32:
        return 0.0
    lii = _LII()
    lii.cbSize = ctypes.sizeof(_LII)
    user32.GetLastInputInfo(ctypes.byref(lii))
    return (kernel32.GetTickCount() - lii.dwTime) / 1000.0


def active_title() -> str:
    if not user32:
        return ""
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def sample() -> str:
    """'study' | 'distract' | 'idle' | 'other' | 'offline' (remote mode: PC off / no heartbeat)."""
    import os
    import time
    if os.getenv("WATCHER_SOURCE", "local") == "remote":
        import notify
        state, ts = notify.PC_STATE
        pc = state if time.time() - ts < 180 else "offline"
    else:
        pc = local_sample()
    # the Android app also reports what you do on the phone: studying counts, doomscrolling flags
    import webserver
    ph = webserver.phone_state()
    if ph:
        if ph[0] == "study":
            return "study"
        if ph[0] == "distract" and pc != "study":
            return "distract"
    return pc


def local_sample() -> str:
    """Reads THIS machine: 'study' | 'distract' | 'idle' | 'other'."""
    if idle_seconds() > 300:
        return "idle"
    t = active_title()
    if STUDY.search(t):
        return "study"
    if DISTRACT.search(t):
        return "distract"
    return "other"
