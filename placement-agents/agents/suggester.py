"""Suggester agent: picks today's Java topic(s) + problems, wording by Claude if a key is set."""
import urllib.parse
import db
import llm
import seed
from agents import tracker


def locked_topics():
    """Problem topics whose course topic you haven't finished yet (unless /unlock all)."""
    if db.get("gate_off") == "1":
        return []
    done = {r["name"] for r in db.q("SELECT name FROM topics WHERE done=1")}
    return [t for t, req in seed.PREREQ.items() if req not in done]


def pick():
    q = tracker.quota()
    topics = db.q("SELECT * FROM topics WHERE done=0 ORDER BY ord LIMIT ?", (q["topics"],))
    locked = locked_topics()
    where = f" AND topic NOT IN ({','.join('?' * len(locked))})" if locked else ""
    probs = db.q(f"SELECT * FROM problems WHERE done=0{where} ORDER BY ord LIMIT ?",
                 (*locked, q["problems"]))
    return q, topics, probs


def _link(name):
    return "https://leetcode.com/problemset/?search=" + urllib.parse.quote(name)


def plan_text() -> str:
    q, topics, probs = pick()
    if q["weight"] == 0:
        return "📵 No study today (exam/day off). Rest well!"
    lines = [f"🎯 Today's plan (~{q['minutes']} min)"]
    if q.get("exam_mode"):
        lines.append("\n📘 EXAM MODE — DSA/Java paused until exams end")
        for t, s, dl in tracker.exam_subjects()[:5]:
            lines.append(f"  • {s:%d %b}  {t} ({dl}d)")
        ex, units = tracker.college_units(3)
        lines.append(f"\n📖 Study now: {ex[0] if ex else '-'}")
        lines += [f"  S{u['id']}. {u['unit']}" for u in units] or \
                 ["  (no syllabus saved yet: /syllabus <subject> | unit 1; unit 2)"]
        lines.append("\nTell me what you study: /studying cloud arch 90")
        lines.append("Mark units: /done S3")
        return "\n".join(lines)
    if topics:
        lines.append("\n☕ Java (Udemy course):")
        lines += [f"  T{t['id']}. {t['name']}" for t in topics]
    if probs:
        lines.append("\n🧩 DSA:")
        lines += [f"  P{p['id']}. [{p['topic']}] {p['name']} ({p['difficulty']})\n     {_link(p['name'])}" for p in probs]
    if len(probs) < q["problems"]:
        lines.append("\n🔒 More problems unlock as you finish course topics (/topics, /done T3). "
                     "Or /unlock all to ignore the order.")
    lines.append("\nWhen done: /done P12 or /done T3")
    return "\n".join(lines)


def coach_line(context: str) -> str:
    """One short motivating line from Claude; harmless fallback if no key/API error."""
    fallback = "Consistency beats intensity. Start with just 25 minutes."
    if not llm.available():
        return fallback
    try:
        return llm.chat("You are a blunt but kind placement coach for an Indian CS student. "
                        "Write ONE short sentence (max 25 words) to get them to study now. "
                        f"Context: {context}", max_tokens=80) or fallback
    except Exception:
        return fallback
