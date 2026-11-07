"""Brain for the phone agent: the Android app sends the goal + a numbered list of what is on screen, and gets back
ONE next action (click / type / scroll / back / ...). The app executes it with its accessibility service and asks again."""
import json
import re

import llm

SYSTEM = """You operate Boss's Android phone for him, one step at a time, through its accessibility service.
You are given the GOAL, what you already did, and the CURRENT SCREEN as a numbered list of elements, for example:
[3] button "Install"      [5] input "Search" (hint: Search apps)      [7] text "Instagram"      [9] switch "Wi-Fi" on
Reply with ONE JSON object and nothing else:
{"action": "click|type|enter|scroll_down|scroll_up|back|home|open_app|wait|done|fail|wait_user", "index": <element number>, "text": "<text to type or app name>", "say": "<very short update for Boss>"}
Actions: click = tap element [index]. type = type "text" into input [index]. enter = press the keyboard's search/enter key. open_app = open the app named in "text".
wait = the screen is still loading. done = the goal is finished (say what happened). fail = it cannot be done (say why).
wait_user = Boss must do something (fingerprint, PIN, password, OTP, captcha, login, permission he must grant).
Rules: one action per reply. Use only element numbers that are on the current screen. If the app you need is not open, use open_app first.
To search: click the search box / icon, type the query, then enter (or click the suggestion/search button).
NEVER type passwords, PINs, OTPs, card or bank details. NEVER tap Buy, Pay, Purchase, Order, Donate, Send money, Confirm payment, Add to cart, Delete account or Factory reset: use wait_user and say what Boss must do himself.
Installing a FREE app (button "Install") is fine. If the same screen repeats after your action, try something different (scroll, another element). Stop with fail after you are stuck.
Keep "say" under 12 words."""


def _parse(text: str) -> dict:
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return {"action": "fail", "say": "I did not get a usable answer from my brain."}
    try:
        d = json.loads(text[i:j + 1])
    except Exception:
        return {"action": "fail", "say": "My brain answered in a form I could not read."}
    act = str(d.get("action", "")).strip().lower()
    if act not in ("click", "type", "enter", "scroll_down", "scroll_up", "back", "home", "open_app", "wait", "done", "fail", "wait_user"):
        return {"action": "fail", "say": f"Unknown step '{act}'."}
    out = {"action": act, "say": str(d.get("say", ""))[:120]}
    if "index" in d:
        try:
            out["index"] = int(d["index"])
        except Exception:
            pass
    if d.get("text") is not None:
        out["text"] = str(d["text"])[:300]
    return out


def step(goal: str, screen: str, history: list) -> dict:
    if not llm.available():
        return {"action": "fail", "say": "The gateway has no AI model configured (LLM_BASE_URL or OPENROUTER_API_KEY)."}
    hist = "\n".join(f"{i + 1}. {str(h)[:100]}" for i, h in enumerate(history[-12:])) or "(nothing yet)"
    user = f"GOAL: {goal}\n\nDONE SO FAR:\n{hist}\n\nCURRENT SCREEN:\n{screen}"
    try:
        m = llm.chat_raw([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=300)
        return _parse(m.get("content") or "")
    except Exception as e:
        return {"action": "fail", "say": f"My brain could not be reached ({str(e)[:80]})."}
