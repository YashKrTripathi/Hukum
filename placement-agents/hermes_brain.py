"""Hermes Agent as Hukum's brain. One-shot call per message (`hermes -z`), session continuity via --continue.
Hermes reaches Hukum's tools through the MCP bridge (hukum_mcp.py). Returns None if Hermes is missing,
has no model configured, or fails -> caller falls back to the built-in OpenRouter brain."""
import os
import shutil
import subprocess
import time

PERSONA = (
    "You are Hukum, Yash's personal Jarvis-like placement assistant. Call him 'Boss'. Reply in the language he "
    "uses (Hinglish/Hindi/English), short and spoken-style, no markdown. You have Hukum tools (hukum MCP): "
    "get_plan, get_status, mark_done, set_call_mode, dial, remember, etc. Use them to actually do things; "
    "never claim you did something without calling the tool.\n\nBoss says: "
)
_fail_until = 0.0


def _exe():
    p = os.getenv("HERMES_CMD") or shutil.which("hermes")
    if p:
        return p
    cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_pzs8sxrjxfjjc",
                        "LocalCache", "Local", "hermes", "bin", "hermes.exe")
    if os.path.exists(cand):
        return cand
    cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "bin", "hermes.exe")
    return cand if os.path.exists(cand) else None


def ask(text, timeout=45):
    global _fail_until
    if os.getenv("HERMES_BRAIN", "1") == "0" or time.time() < _fail_until:
        return None
    exe = _exe()
    if not exe:
        return None
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # fastest first: no reasoning; then the plain one-shot forms
    variants = (
        ["chat", "-Q", "--oneshot", "--reasoning", "none", "--continue", "hukum", "-q", PERSONA + text],
        ["-z", PERSONA + text, "--continue", "hukum"],
        ["-z", PERSONA + text],
    )
    for args in variants:
        try:
            r = subprocess.run([exe, *args], capture_output=True, timeout=timeout,
                               env=env, encoding="utf-8", errors="replace")
        except Exception:
            break
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            return out
    _fail_until = time.time() + 300      # don't retry for 5 min (no model/key yet)
    return None


import re
_HEAVY = re.compile(r"\b(hermes|research|search|google|dhundh|khoj|summari[sz]e|explain in detail|plan banao|"
                    r"roadmap|compare|yaad rakh|yaad rakhna|remember|schedule|cron|every day|har din)\b", re.I)


def wants_hermes(text):
    """Heavy / open-ended requests go to Hermes; quick chat and commands use the fast brain."""
    return bool(_HEAVY.search(text or "")) and not (text or "").startswith("__")
