"""Command center. Turns what Boss says or types into a plan of tool calls, runs them through the permission manager,
checks the results and answers plainly. Plan sources: (1) rules for the common commands - instant, works with no AI
endpoint; (2) the configured AI model, which sees the tool catalog and answers in JSON. Multi-step plans stop at the
first failure and say exactly what happened."""
import json
import re
import time

from . import store, tools, ai, memory, notify, monitor, projects, permissions, agents, sysmon

KNOWN = r"(?:vs ?code|code|chrome|edge|terminal|powershell|cmd|notepad|explorer|task ?manager|antigravity|claude|codex|file explorer)"


def _m(rx, t):
    return re.match(rx, t, re.I | re.S)


def plan_rules(text):
    """Return a list of steps [{tool,args}] or None when no rule matches."""
    t = text.strip().rstrip(".!")
    low = t.lower()
    if m := _m(r"(?:open|launch|start)\s+(" + KNOWN + r")(?:\s+(?:on|in|with|at)\s+(.+))?$", t):
        return [{"tool": "app_launch", "args": {"name": m[1], **({"path": m[2].strip('"')} if m[2] else {})}}]
    if m := _m(r"(?:open|go to)\s+(https?://\S+)", t):
        return [{"tool": "web_open", "args": {"url": m[1]}}]
    if m := _m(r"(?:close|quit|exit)\s+(" + KNOWN + r")$", t):
        return [{"tool": "app_close", "args": {"name": m[1]}}]
    if m := _m(r"(?:focus|switch to|bring up|show me)\s+(" + KNOWN + r")$", t):
        return [{"tool": "app_focus", "args": {"name": m[1]}}]
    if m := _m(r"type\s+[\"“'](.+?)[\"”']\s+(?:in|into|on)\s+(.+)$", t):
        return [{"tool": "ui_type", "args": {"app": m[2].strip(), "text": m[1]}}]
    if m := _m(r"(?:press|hit)\s+([a-z0-9+]+)\s+(?:in|on)\s+(.+)$", t):
        return [{"tool": "ui_keys", "args": {"app": m[2].strip(), "keys": m[1]}}]
    if m := _m(r"click\s+(?:the\s+)?[\"“']?(.+?)[\"”']?(?:\s+button)?\s+(?:in|on)\s+(.+)$", t):
        return [{"tool": "ui_click", "args": {"app": m[2].strip(), "control": m[1]}}]
    if m := _m(r"(?:read|ocr)\s+(?:the\s+)?(?:screen|window)(?:\s+of\s+(.+))?$", t) or _m(r"what(?:'s| is) on (?:my |the )?screen(?: in (.+))?$", t):
        return [{"tool": "screen_read", "args": {"app": (m[1] or "").strip() or None}}]
    if m := _m(r"read\s+(" + KNOWN + r")$", t):
        return [{"tool": "ui_read", "args": {"app": m[1]}}]
    if re.search(r"which apps|what('s| is) running|running apps|apps running|app status|applications", low):
        return [{"tool": "app_list", "args": {}}]
    if re.search(r"why .*(slow|lag|hang)|system (status|health)|how(?:'s| is) my (pc|laptop|computer|system)|cpu|ram usage|memory usage|gpu|battery|disk space", low):
        return [{"tool": "system_status", "args": {}}]
    if re.search(r"dev(elopment)? servers?|which ports|ports in use|servers running", low):
        return [{"tool": "dev_servers", "args": {}}]
    if len(low.split()) <= 6 and re.search(r"^(list|show|what are|what's|which|what)?\s*(me )?(my |the )?(all )?projects\b", low):
        return [{"tool": "project_list", "args": {}}]
    if m := _m(r"(?:tell me about|info on|details of|about)\s+(?:project\s+)?(.+?)\s*project$", t) or _m(r"project\s+info\s+(.+)$", t):
        return [{"tool": "project_info", "args": {"project": m[1]}}]
    if m := _m(r"(start|pause|resume|stop)\s+monitoring$", t):
        return [{"tool": "monitor_control", "args": {"mode": m[1].lower()}}]
    if re.search(r"monitoring status|what have you noticed|what are you seeing|what am i (doing|working on)", low):
        return [{"tool": "monitor_status", "args": {}}]
    if m := _m(r"remember(?: that)?\s+(.+)$", t):
        return [{"tool": "remember", "args": {"text": m[1]}}]
    if re.search(r"what do you (remember|know about me)|my memories|show memory", low):
        return [{"tool": "recall", "args": {}}]
    if m := _m(r"(?:add|create|new)\s+(?:a\s+)?task[:\s]+(.+?)(?:\s+due\s+(\d{4}-\d\d-\d\d))?$", t) or _m(r"remind me to\s+(.+?)(?:\s+(?:by|due)\s+(\d{4}-\d\d-\d\d))?$", t):
        return [{"tool": "task_add", "args": {"title": m[1], **({"due": m[2]} if m[2] else {})}}]
    if re.search(r"^(show |list |what are )?(my )?(open )?tasks\b|to-?do", low):
        return [{"tool": "task_list", "args": {}}]
    if m := _m(r"(?:finish|complete|done|close)\s+task\s+#?(\d+)", t):
        return [{"tool": "task_done", "args": {"id": int(m[1])}}]
    if m := _m(r"(?:ask|tell|have|let)\s+(codex|antigravity|agy|claude)\s+(?:to\s+)?(.+?)\s+(?:in|on|for)\s+(?:the\s+)?(?:project\s+)?([\w .\\:-]+?)(?:\s+project)?$", t):
        ro = bool(re.search(r"\b(review|explain|analy[sz]e|audit|summari[sz]e|find|look)\b", m[2], re.I))
        return [{"tool": "agent_run", "args": {"agent": m[1], "project": m[3].strip(), "prompt": m[2], "readonly": ro}}]
    if re.search(r"agent (status|jobs)|what are the agents doing|coding agents", low):
        return [{"tool": "agent_status", "args": {}}]
    if m := _m(r"cancel\s+(?:agent\s+)?job\s+#?(\d+|all)", t) or _m(r"stop (all )?agents()", t):
        return [{"tool": "agent_cancel", "args": {"job_id": m[1] if (m[1] or "").strip() and m[1] != "all " else "all"}}]
    # "show me Claude's response", "claude ka jawab dikhao", "codex ne kya kaha" (speech often hears Claude as "cloud")
    if (m := re.search(r"\b(claude|cloud|clod|codex|antigravity|agy)\b|क्लाउड|क्लॉड|कोडेक्स", low)) and not re.match(r"(ask|tell|have|let|open|launch|start|close|quit)\b", low) \
            and re.search(r"respon|repl(y|ies)|answer|jawa?ab|output|result|said|say|bol|kah[ae]|likh|dikha|padh|bata|show|read|दिखा|पढ़|बता|जवाब|क्या", low):
        who = m.group(0).lower()
        who = "claude" if who in ("cloud", "clod", "क्लाउड", "क्लॉड") else "codex" if who in ("कोडेक्स",) else who
        return [{"tool": "ui_read", "args": {"app": who}}]
    if m := _m(r"(?:send|message|whatsapp|text)\s+(?:a\s+)?(?:whatsapp\s+)?(?:message\s+)?(?:to\s+)?([\w +]+?)\s*(?::|saying|that says|-)\s*(.+)$", t):
        return [{"tool": "msg_send", "args": {"contact": m[1].strip(), "text": m[2].strip()}}]
    if re.search(r"(any )?(new )?(messages|whatsapp)|who messaged|inbox", low):
        return [{"tool": "msg_inbox", "args": {}}]
    if m := _m(r"run\s+(?:command\s+)?`?(.+?)`?(?:\s+in\s+(.+))?$", t):
        return [{"tool": "shell_run", "args": {"command": m[1], **({"cwd": m[2]} if m[2] else {})}}]
    if re.search(r"emergency stop|stop everything|abort everything", low):
        return [{"tool": "__estop", "args": {}}]
    if re.search(r"briefing|what did i miss|summary of (my )?day|catch me up", low):
        return [{"tool": "__briefing", "args": {}}]
    if re.search(r"notifications|alerts|anything wrong|any problems", low):
        return [{"tool": "__notifications", "args": {}}]
    return None


# ---------------------------------------------------------------- briefing
def briefing():
    """A real summary built from stored data (no AI required)."""
    now = time.time()
    lines = []
    s = sysmon.sample()
    lines.append("System: " + sysmon.describe(s) + ". " + " ".join(sysmon.diagnose(s)))
    n = notify.counts()
    unacked = notify.recent(8, unacked=True)
    if unacked:
        lines.append(f"{sum(n.values())} unread alert(s): " + "; ".join(f"[{u['severity']}] {u['title']}" for u in unacked[:5]))
    else:
        lines.append("No unread alerts.")
    jobs = [j for j in agents.jobs(20) if now - j["updated"] < 86400]
    if jobs:
        lines.append("Coding agents (24h): " + ", ".join(f"#{j['id']} {j['agent']} {j['status']}" for j in jobs[:6]))
    tasks = memory.list_tasks(open_only=True)
    od = [t for t in tasks if t["overdue"]]
    lines.append(f"Tasks: {len(tasks)} open" + (f", {len(od)} overdue ({', '.join(t['title'] for t in od[:3])})" if od else "") + ".")
    dirty = [p["name"] + f" ({(p.get('git') or {}).get('dirty')} changed)" for p in projects.list_projects() if (p.get("git") or {}).get("dirty")]
    if dirty:
        lines.append("Uncommitted changes: " + ", ".join(dirty[:6]))
    try:
        servers = projects.dev_servers()
        if servers:
            lines.append("Dev servers: " + ", ".join(f"{s['project'] or s['name']}:{s['ports'][0]}" for s in servers[:6]))
    except Exception:
        pass
    ctx = monitor.context()
    if ctx.get("app"):
        lines.append(f"Right now (inferred): {ctx['activity']}.")
    act = store.q("SELECT kind,COUNT(*) n FROM activity WHERE ts>? GROUP BY kind", (now - 86400,))
    if act:
        lines.append("Activity today: " + ", ".join(f"{a['n']} {a['kind']}" for a in act))
    return "\n".join(lines)


# ---------------------------------------------------------------- formatting
def _fmt(step, res):
    name, r = step["tool"], res.get("result")
    if name == "app_list":
        run = [a for a in r if a["running"]]
        return "Running: " + (", ".join(f"{a['name']}" + (f" ({a['active_window'][:40]})" if a["active_window"] else "") for a in run) or "none of the known apps")
    if name == "system_status":
        return r["summary"] + "\n" + "\n".join(r["findings"])
    if name in ("app_launch", "app_focus"):
        return f"Done. {r.get('title') or r.get('name') or ''} is {'in front' if name == 'app_focus' else 'open'}" + (" (verified)" if r.get("verified") else "") + "."
    if name == "app_close":
        return f"Asked to close; closed {r.get('closed')}, remaining {r.get('remaining')}." + (f" {r['note']}" if r.get("note") else "")
    if name in ("ui_read", "screen_read"):
        return f"{r['app']} - {r['title']}:\n" + (r["text"][:1800] or "(no text found)")
    if name == "ui_type":
        return f"Typed into {r['typed_into']} (foreground is {r['foreground']})."
    if name == "project_list":
        return "\n".join("- " + p["summary"] for p in r) or "No projects found in the allowed folders."
    if name == "dev_servers":
        return "\n".join(f"- {s['name']} on {s['ports']} {('for ' + s['project']) if s['project'] else ''}" for s in r) or "No development servers are listening."
    if name == "task_list":
        return "\n".join(f"- #{t['id']} {t['title']}" + (f" (due {t['due']}{', OVERDUE' if t['overdue'] else ''})" if t["due"] else "") for t in r) or "No open tasks."
    if name == "task_add":
        return f"Task #{r['id']} added: {r['title']}"
    if name == "recall":
        return "\n".join(f"- ({m['kind']}) {m['text']}" for m in r[:15]) or "Nothing remembered yet."
    if name == "remember":
        return f"Remembered: {r['text']}"
    if name == "agent_run":
        return f"Job #{r['id']} queued for {r['agent']} on {r['repo']} ({'read-only' if r['readonly'] else 'can edit files'}). Follow it in AI Agents."
    if name == "agent_status":
        return ("Drivers: " + ", ".join(f"{k} {'ready' if v['available'] else 'unavailable'}" for k, v in r["drivers"].items()) + "\n" +
                "\n".join(f"#{j['id']} {j['agent']} {j['status']}: {j['prompt'][:60]}" for j in r["jobs"]))
    if name == "monitor_status":
        st = r["status"]
        rec = "\n".join(f"- [{o['severity']}] {o['title']}: {o['observed']}" for o in r["recent"][:5])
        return f"Monitoring is {st['mode']} ({st['passes']} passes). " + (f"Now (inferred): {r['context'].get('activity')}.\n" if r["context"].get("app") else "") + (rec or "Nothing notable observed yet.")
    if name == "monitor_control":
        return f"Monitoring is now {r['mode']}."
    if name == "msg_send":
        return f"Message handled: {r['result']}"
    if name == "msg_inbox":
        return r["text"][:1800]
    if name == "shell_run":
        return f"Exit code {r['exit_code']}.\n{r['output'][:1500]}"
    if name == "web_open":
        return f"Opened {r['opened']}."
    if name == "agent_cancel":
        return f"Cancelled: {r['cancelled']}."
    return json.dumps(r, ensure_ascii=False, default=str)[:1500]


# ---------------------------------------------------------------- LLM planner
PLAN_SYS = """You are Hukum, Boss's personal assistant running on his Windows PC. You control the PC ONLY through these tools:
{catalog}
Reply with ONE JSON object: {{"reply": "short answer for Boss", "steps": [{{"tool": "name", "args": {{...}}}}]}}.
Use steps only when an action is really needed; otherwise answer in reply with an empty steps list. Never invent tool names.
Never put secrets in args. Message sending always needs a real recipient and the exact text. Keep reply under 80 words.
Known context:
{context}"""


def plan_llm(text):
    cat = "\n".join(f"- {t['name']}({', '.join(t['params'])}): {t['desc']} [risk {t['risk']}]" for t in tools.catalog())
    hist = store.q("SELECT role,text FROM conv ORDER BY id DESC LIMIT 6")[::-1]
    ctx = "Remembered:\n" + memory.context_block(8) + "\nNow: " + json.dumps(monitor.context(), default=str)[:300] + "\nProjects: " + ", ".join(p["name"] for p in projects.list_projects()[:12])
    msgs = [{"role": "system", "content": PLAN_SYS.format(catalog=cat, context=ctx)}]
    msgs += [{"role": h["role"], "content": h["text"][:600]} for h in hist if h["role"] in ("user", "assistant")]
    msgs.append({"role": "user", "content": text})
    r = ai.chat(msgs, timeout=60)
    c = r["content"].strip()
    i, j = c.find("{"), c.rfind("}")
    if i >= 0 and j > i:
        try:
            d = json.loads(c[i:j + 1])
            return d.get("reply", ""), [s for s in d.get("steps", []) if isinstance(s, dict) and s.get("tool") in tools.TOOLS][:6]
        except Exception:
            pass
    return c[:600], []


# ---------------------------------------------------------------- entry point
def handle(text, source="dashboard", preapproved=False, actor="boss"):
    """Process one command. Returns {reply, steps:[{tool,args,ok,risk,say|error}], via}."""
    text = (text or "").strip()
    if not text:
        return {"reply": "Say or type what you need.", "steps": [], "via": "none"}
    store.x("INSERT INTO conv(ts,role,text,project) VALUES(?,?,?,?)", (time.time(), "user", text, ""))
    store.activity("command", text)
    plan, via, reply = plan_rules(text), "rules", ""
    if plan is None and ai.available():
        try:
            reply, plan = plan_llm(text)
            via = "ai"
        except Exception as e:
            reply, plan, via = f"The AI model could not be reached ({e}). I can still do direct commands such as 'open chrome', 'system status', 'projects'.", [], "error"
    if plan is None:
        plan, via = [], "none"
        reply = "I did not understand that and no AI model is configured (Settings > AI). Try: open chrome, system status, projects, tasks, briefing."
    results = []
    out_lines = [reply] if reply else []
    for step in plan:
        name, args = step["tool"], step.get("args") or {}
        if name == "__estop":
            permissions.estop("commanded by Boss")
            agents.cancel_all()
            results.append({"tool": "emergency_stop", "args": {}, "ok": True, "say": "Emergency stop is ON. Everything is paused and pending approvals were rejected."})
            out_lines.append(results[-1]["say"])
            break
        if name in ("__briefing", "__notifications"):
            say = briefing() if name == "__briefing" else ("\n".join(f"[{n['severity']}] {n['title']} - {n['body'][:100]}" for n in notify.recent(8, unacked=True)) or "No unread alerts.")
            results.append({"tool": name.strip("_"), "args": {}, "ok": True, "say": say})
            out_lines.append(say)
            continue
        res = tools.call(name, args, actor=actor, preapproved=preapproved, source=source)
        entry = {"tool": name, "args": args, "ok": res["ok"], "risk": res.get("risk")}
        if res["ok"]:
            entry["say"] = _fmt(step, res)
            entry["data"] = res["result"]
            out_lines.append(entry["say"])
        else:
            entry["error"] = res["error"]
            out_lines.append(("Not done - " if res.get("denied") else "Failed - ") + res["error"])
            results.append(entry)
            break
        results.append(entry)
    answer = "\n".join(l for l in out_lines if l) or "Done."
    store.x("INSERT INTO conv(ts,role,text,project) VALUES(?,?,?,?)", (time.time(), "assistant", answer[:3000], ""))
    return {"reply": answer, "steps": results, "via": via}
