"""Conversational agent: you talk (text or voice, Hinglish/Hindi/English), it answers and
takes actions on your plan through tools. Needs OPENROUTER_API_KEY (a model with tool calling)."""
import json
import re
import threading
import time
from datetime import date, datetime
import db
import llm
import inbox
from agents import tracker, suggester

_tl = threading.local()     # actions for the Android app collected while handling one request

SYSTEM = """You are Hukum, Boss's personal AI (Yash, a CS student in India): his Jarvis and his own brother.
You live on his phone and PC, know everything he tells you, and do things for him through tools.
STYLE: talk like a real brother on a phone call: warm, direct, sometimes funny. Mirror Boss's language
exactly: Hinglish in Roman letters -> Hinglish in Roman letters; Hindi -> Hindi; English -> English.
Short: 1-4 sentences, no lists unless asked, at most one emoji. Never robotic, never preachy.
RULES: Never invent messages, calls, progress or dates; call tools to get facts. After using a tool,
confirm in a few words. Be proactive: if the inbox has unanswered messages and it fits, mention them.
MESSAGES: you see his WhatsApp/Discord/SMS notifications. To read them call get_messages. To answer
someone, first DRAFT the reply in his voice and say it to Boss; only after he says yes/ok/bhej do
call reply_message with confirmed=true. Never send anything he did not approve. When he says he
handled a chat himself call mark_messages_handled. Never read out OTPs, passwords or card numbers.
CALLS: if Boss says he is sleeping, in a meeting, driving or busy and wants calls handled, call
set_call_mode (sleeping/busy/driving). Incoming callers are rejected silently and get an SMS from you
(a short polite text, Roman letters, max 150 chars, saying you are Hukum, Boss's assistant, he is
unavailable and will call back; use his reason if given). Then wish him goodnight/okay briefly. When
he is awake or back call set_call_mode normal. When he asks to call someone, use dial.
PC: you also control Boss's PC through tools when its agent is online (pc_status tells). pc_open, pc_read,
pc_status, code_status are free to use. pc_run (shell) and code_task (start a coding agent in a repo) need
his OK: say exactly what you will run/ask, wait for yes, then call with confirmed=true. For a coding task
write a clear self-contained prompt for the agent. Tell him results briefly; long tasks report back by themselves.
MEMORY: save lasting facts, people and preferences he tells you with remember.
STUDY (a side skill, only when he brings it up): tools get_plan, get_status, list_topics, mark_done,
set_study_time, start_focus, log_minutes, add_event, list_events, delete_event, add_syllabus.
Things you remember about Boss:
{memory}
Now: {now}
Phone: {device}
Inbox (unanswered):
{inbox}"""

WAKE_PROMPT = ("(Boss just woke up and unlocked his phone. While he was unavailable these calls came, "
               "as JSON with caller name or number, time and count: {calls}. Tell him in Hinglish, 2-3 "
               "short sentences: who called (use the name; say the number only if there is no name), how "
               "many times and roughly when, then ask if he wants you to call them back. If the list "
               "is empty say no calls came.)")


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


TOOLS = [
    _fn("get_plan", "Today's study plan (problems, course topics, exam subjects)."),
    _fn("get_status", "Progress: course topics, problems solved, streak, minutes today."),
    _fn("list_topics", "Next unfinished course topics with ids."),
    _fn("mark_done", "Mark items done. ids like P12 (problem), T3 (course topic), S4 (college unit).",
        {"ids": {"type": "array", "items": {"type": "string"}}}, ["ids"]),
    _fn("set_study_time", "Set today's study start time (24h HH:MM, must be in the future).",
        {"time": {"type": "string"}}, ["time"]),
    _fn("start_focus", "Yash is studying now; log it and stop nagging for N minutes. subject optional (college subject words).",
        {"minutes": {"type": "integer"}, "subject": {"type": "string"}}, ["minutes"]),
    _fn("log_minutes", "Add manually studied minutes for today.", {"minutes": {"type": "integer"}}, ["minutes"]),
    _fn("add_event", "Add exam, practical or vacation. Dates YYYY-MM-DD.",
        {"kind": {"type": "string", "enum": ["exam", "practical", "vacation"]}, "title": {"type": "string"},
         "start": {"type": "string"}, "end": {"type": "string"}}, ["kind", "title", "start", "end"]),
    _fn("list_events", "List calendar events with ids."),
    _fn("delete_event", "Delete a calendar event by id.", {"id": {"type": "integer"}}, ["id"]),
    _fn("add_syllabus", "Save syllabus units for an exam subject.",
        {"subject": {"type": "string"}, "units": {"type": "array", "items": {"type": "string"}}},
        ["subject", "units"]),
    _fn("set_call_mode", "Silently reject incoming calls for Boss and SMS the callers a polite message, or switch it off.",
        {"mode": {"type": "string", "enum": ["sleeping", "busy", "driving", "normal"]},
         "greeting": {"type": "string", "description": "SMS text sent to callers (Roman letters, max 150 chars). Omit for normal."}},
        ["mode"]),
    _fn("dial", "Call someone back from Boss's phone. target = contact name or phone number.",
        {"target": {"type": "string"}}, ["target"]),
    _fn("get_messages", "Read Boss's messages from WhatsApp/Discord/SMS notifications. Defaults to unread ones.",
        {"app": {"type": "string", "description": "whatsapp, discord, sms, call (optional)"},
         "sender": {"type": "string", "description": "name filter (optional)"},
         "include_read": {"type": "boolean"}, "limit": {"type": "integer"}}),
    _fn("mark_messages_handled", "Mark messages as dealt with so Hukum stops reminding. By sender name or ids like M12.",
        {"sender": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}}),
    _fn("reply_message", "Send a reply to a person on the phone (WhatsApp/Discord/SMS reply action). ONLY with confirmed=true "
        "after Boss approved the exact text; first call with confirmed=false to get the draft check.",
        {"sender": {"type": "string"}, "text": {"type": "string"}, "app": {"type": "string"},
         "confirmed": {"type": "boolean"}}, ["sender", "text", "confirmed"]),
    _fn("pc_status", "Is Boss's PC online, and what PC jobs/coding tasks are running or recently finished."),
    _fn("pc_open", "Open an app (by configured name), a file, a folder or a URL on Boss's PC.",
        {"target": {"type": "string"}}, ["target"]),
    _fn("pc_read", "List a folder or read a small text file on Boss's PC (only inside the allowed folders).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("pc_run", "Run a shell command on Boss's PC. ONLY with confirmed=true after Boss approved the exact command.",
        {"command": {"type": "string"}, "cwd": {"type": "string", "description": "repo alias or folder (optional)"},
         "confirmed": {"type": "boolean"}}, ["command", "confirmed"]),
    _fn("code_task", "Start a coding agent (Claude Code or Hermes) on Boss's PC in a repo. Runs in the background; "
        "Boss gets a notification when it finishes. ONLY with confirmed=true after Boss approved the task.",
        {"repo": {"type": "string", "description": "repo alias from the PC config, or a folder"},
         "prompt": {"type": "string"}, "agent": {"type": "string", "enum": ["claude", "hermes"]},
         "confirmed": {"type": "boolean"}}, ["repo", "prompt", "confirmed"]),
    _fn("code_status", "Progress/output of a coding task (job id like J5) or the latest ones.",
        {"job": {"type": "string"}}),
    _fn("code_stop", "Stop a running coding task or PC command by job id.", {"job": {"type": "string"}}, ["job"]),
    _fn("remember", "Save a lasting fact or preference about Boss for future chats.",
        {"fact": {"type": "string"}}, ["fact"]),
]

DEFAULT_GREETING = {
    "sleeping": "Hi, this is Hukum, Boss's assistant. Boss is sleeping right now and will call you back later.",
    "busy": "Hi, this is Hukum, Boss's assistant. Boss is busy right now and will call you back soon.",
    "driving": "Hi, this is Hukum, Boss's assistant. Boss is driving right now and will call you back later.",
}


def _memory() -> list:
    try:
        return json.loads(db.get("memory", "[]"))
    except Exception:
        return []


def run_tool(name: str, a: dict) -> str:
    try:
        if name == "get_plan":
            return suggester.plan_text()
        if name == "get_status":
            return tracker.status_text()
        if name == "list_topics":
            rows = db.q("SELECT id,name FROM topics WHERE done=0 ORDER BY ord LIMIT 10")
            return "\n".join(f"T{r['id']}. {r['name']}" for r in rows) or "Course finished"
        if name == "mark_done":
            out = []
            for x in a["ids"]:
                m = re.fullmatch(r"([PpTtSs])(\d+)", x.strip())
                if not m:
                    continue
                k, i = m[1].lower(), int(m[2])
                if k == "s":
                    db.x("UPDATE syllabus SET done=1 WHERE id=?", (i,))
                elif k == "p":
                    tracker.mark_problem(i)
                else:
                    tracker.mark_topic(i)
                out.append(x.upper())
            return "Marked done: " + ", ".join(out) if out else "No valid ids"
        if name == "set_study_time":
            t = re.fullmatch(r"(\d{1,2}):(\d{2})", a["time"].strip())
            if not t:
                return "Invalid time"
            hhmm = f"{int(t[1]):02d}:{t[2]}"
            if hhmm <= datetime.now().strftime("%H:%M"):
                return "That time already passed today"
            db.put("study_time", hhmm); db.put("acked", ""); db.put("stage", 0); db.put("awaiting_time", 0)
            return f"Study time set to {hhmm}"
        if name == "start_focus":
            subj = tracker.resolve_subject(a.get("subject", "")) if a.get("subject") else None
            mins = int(a["minutes"])
            db.put("focus_until", time.time() + mins * 60)
            db.put("acked", date.today().isoformat()); db.put("bad", 0)
            return f"Focus mode on for {mins} min" + (f" ({subj})" if subj else "")
        if name == "log_minutes":
            tracker.log_minutes(int(a["minutes"]), "manual"); db.put("acked", date.today().isoformat())
            return f"Logged. Today total {tracker.minutes_today()} min"
        if name == "add_event":
            date.fromisoformat(a["start"]); date.fromisoformat(a["end"])
            tracker.add_event(a["kind"], a["title"], a["start"], a["end"])
            return f"Added {a['kind']} {a['title']} {a['start']} to {a['end']}"
        if name == "list_events":
            rows = db.q("SELECT * FROM events ORDER BY start")
            return "\n".join(f"#{r['id']} {r['kind']} {r['title']} {r['start']}..{r['end']}" for r in rows) or "none"
        if name == "delete_event":
            db.x("DELETE FROM events WHERE id=?", (int(a["id"]),)); return "Deleted"
        if name == "set_call_mode":
            mode = a["mode"]
            greeting = (a.get("greeting") or DEFAULT_GREETING.get(mode, "")).strip()
            db.put("call_mode", mode)
            _tl.actions.append({"type": "call_mode", "mode": mode, "greeting": greeting})
            return "Call assistant switched off" if mode == "normal" else f"Call assistant ON ({mode}); greeting set"
        if name == "dial":
            _tl.actions.append({"type": "dial", "target": a["target"]})
            return f"Dialing {a['target']}"
        if name == "get_messages":
            import inbox
            rows = inbox.messages(a.get("app"), a.get("sender"), only_open=not a.get("include_read"),
                                  limit=int(a.get("limit") or 12))
            return inbox.format_rows(rows)
        if name == "mark_messages_handled":
            import inbox
            return inbox.mark_handled(a.get("sender"), a.get("ids"))
        if name == "reply_message":
            import inbox
            if not a.get("confirmed"):
                return "NOT SENT. Say the draft to Boss, wait for his yes, then call again with confirmed=true."
            r = inbox.reply_target(a["sender"], a.get("app"))
            if not r:
                return "Can't reply: no recent replyable notification from that person (the chat notification is gone)."
            _tl.actions.append({"type": "reply", "nkey": r["nkey"], "app": r["app"], "sender": r["sender"],
                                "text": a["text"].strip()[:1000]})
            inbox.mark_handled(ids=[r["id"]], sender=r["sender"])
            return f"Reply sent to {r['sender']} via {r['app']}"
        if name in ("pc_status", "pc_open", "pc_read", "pc_run", "code_task", "code_status", "code_stop"):
            import pcbridge
            if name == "pc_status":
                return pcbridge.status_text()
            if name == "pc_open":
                return pcbridge.run("open", {"target": str(a["target"])[:500]})
            if name == "pc_read":
                return pcbridge.run("read", {"path": str(a["path"])[:500]})
            if name == "pc_run":
                if not a.get("confirmed"):
                    return "NOT RUN. Tell Boss the exact command, wait for his yes, then call again with confirmed=true."
                return pcbridge.run("run", {"command": str(a["command"])[:2000], "cwd": str(a.get("cwd") or "")[:300]})
            if name == "code_task":
                if not a.get("confirmed"):
                    return "NOT STARTED. Tell Boss the repo and what the agent will do, wait for his yes, then call again with confirmed=true."
                if not pcbridge.online():
                    return "PC is offline (the Hukum PC agent is not running). Ask Boss to start it."
                j = pcbridge.submit("code", {"repo": str(a["repo"])[:300], "prompt": str(a["prompt"])[:6000],
                                             "agent": str(a.get("agent") or "claude")})
                return f"Coding task {j['id']} queued. Boss gets a notification when it finishes."
            if name == "code_status":
                jid = str(a.get("job") or "").strip().upper()
                if jid and jid in pcbridge._jobs:
                    return pcbridge.describe(pcbridge._jobs[jid], tail=2500)
                return pcbridge.status_text()
            if name == "code_stop":
                return pcbridge.stop(str(a["job"]).strip().upper())
        if name == "remember":
            mem = _memory()
            fact = a["fact"].strip()
            if fact and fact not in mem:
                mem.append(fact)
            db.put("memory", json.dumps(mem[-40:], ensure_ascii=False))
            return "Remembered"
        if name == "add_syllabus":
            subj = tracker.resolve_subject(a["subject"])
            if not subj:
                names = "; ".join(t for t, _, _ in tracker.exam_subjects())
                return f"Subject not matched. Exam subjects: {names}"
            for u in a["units"]:
                db.x("INSERT OR IGNORE INTO syllabus(subject,unit) VALUES(?,?)", (subj, u.strip()))
            return f"Saved {len(a['units'])} units for {subj}"
    except Exception as e:
        return f"Tool error: {e}"
    return "Unknown tool"


def respond(user_text: str) -> str:
    """Blocking (run in a thread). Keeps a short rolling chat memory."""
    _tl.actions = []
    hist = json.loads(db.get("chat_hist", "[]"))[-12:]
    ctx = f"{suggester.plan_text()}\n\n{tracker.status_text()}"
    memory = "\n".join(f"- {m}" for m in _memory()) or "(nothing yet)"
    device = db.get("device", "Android phone (connected)")
    msgs =[{"role": "system", "content": SYSTEM.format(
        now=datetime.now().strftime("%A %d %b %Y, %H:%M"), device=device, inbox=inbox.summary(), memory=memory)}] + hist + \
           [{"role": "user", "content": user_text}]
    reply = ""
    for _ in range(5):
        m = llm.chat_raw(msgs, TOOLS)
        calls = m.get("tool_calls")
        if not calls:
            reply = (m.get("content") or "").strip()
            break
        msgs.append(m)
        for c in calls:
            args = json.loads(c["function"].get("arguments") or "{}")
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": run_tool(c["function"]["name"], args)})
    reply = reply or "Samajh nahi aaya, ek baar phir bolo?"
    hist += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
    db.put("chat_hist", json.dumps(hist[-20:], ensure_ascii=False))
    return reply


def respond_full(user_text: str):
    """(reply, actions) - actions are commands for the Android app (call mode, dial...)."""
    reply = respond(user_text)
    return reply, list(getattr(_tl, "actions", []))


def spoken(text: str) -> str:
    """Rewrite for the voice: Hindi/Hinglish -> Devanagari (English tech terms stay Latin)."""
    try:
        return llm.chat(
            "Rewrite this for a text-to-speech voice. If it is Hindi or Hinglish, write natural spoken "
            "Hindi in Devanagari script, keeping English technical words (DSA, LeetCode, array, exam) in "
            "Latin letters. If it is English, keep English. No emojis, markdown or links. Max 70 words. "
            "Output only the rewritten text.\n\n" + text, max_tokens=250) or text
    except Exception:
        return text
