"""Tracker agent: knows progress, college calendar (exams/vacations) and how much
you must do per day so you still land at the deadline."""
import math
from datetime import date, datetime, timedelta
import db
from config import (FINAL_DEADLINE, JAVA_DEADLINE, BUFFER_DAYS, TARGET_LEETCODE,
                    DAILY_TARGET_MINUTES)


def today() -> date:
    return date.today()


def _events(kind=None):
    rows = db.q("SELECT * FROM events" + (" WHERE kind=?" if kind else ""), (kind,) if kind else ())
    return [(r["kind"], r["title"], date.fromisoformat(r["start"]), date.fromisoformat(r["end"])) for r in rows]


PREP_DAYS = {"exam": 10, "practical": 3}   # DSA is paused this many days before


def _exam_events():
    return [(k, t, s, e) for k, t, s, e in _events() if k in PREP_DAYS]


def exam_window(d: date) -> bool:
    """True from N days before an exam/practical through its last day: college study only."""
    return any(s - timedelta(days=PREP_DAYS[k]) <= d <= e for k, _, s, e in _exam_events())


def day_weight(d: date) -> float:
    """DSA/Java weight: 0 during exam window (DSA is postponed), 0.3 on vacation, else 1."""
    if exam_window(d):
        return 0.0
    w = 1.0
    for kind, _, s, e in _events("vacation"):
        if s <= d <= e:
            w = 0.3
    return w


def study_weight(d: date) -> float:
    """How much study the agent expects (and nags about): full on exam-window days."""
    return 1.0 if exam_window(d) else day_weight(d)


def resolve_subject(text: str):
    """Fuzzy-match words to exactly one exam subject. None if no match or ambiguous."""
    words = text.lower().split()
    if not words:
        return None
    titles = list(dict.fromkeys(t for _, t, _, _ in _exam_events()))
    hits = [t for t in titles if all(w in t.lower() for w in words)]
    return hits[0] if len(hits) == 1 else None


def exam_subjects():
    """Upcoming exams as [(subject, date, days_left)] sorted by date."""
    return [(t, s, (s - today()).days) for _, t, s, e in sorted(_exam_events(), key=lambda x: x[2])
            if e >= today()]


def weighted_days(start: date, end: date) -> float:
    n, d = 0.0, start
    while d <= end:
        n += day_weight(d)
        d += timedelta(days=1)
    return max(n, 0.5)


def progress() -> dict:
    done_p = db.q("SELECT COUNT(*) n FROM problems WHERE done=1")[0]["n"]
    tot_p = db.q("SELECT COUNT(*) n FROM problems")[0]["n"]
    done_t = db.q("SELECT COUNT(*) n FROM topics WHERE done=1")[0]["n"]
    tot_t = db.q("SELECT COUNT(*) n FROM topics")[0]["n"]
    solved = max(done_p, int(db.get("lc_total", 0)))   # LeetCode sync may know more
    return dict(done_p=solved, tot_p=tot_p, done_t=done_t, tot_t=tot_t)


def college_units(n=3):
    """(focus_exam, units): unfinished units of the earliest upcoming exam that has any."""
    subs = exam_subjects()
    for title, s, _ in subs:
        rows = db.q("SELECT * FROM syllabus WHERE done=0 AND lower(subject)=lower(?) ORDER BY id LIMIT ?",
                    (title, n))
        if rows:
            return (title, s), rows
    return (subs[0][0], subs[0][1]) if subs else None, []


def quota(d: date | None = None) -> dict:
    """How many Java topics and problems should be done on day d."""
    d = d or today()
    pr = progress()
    w = day_weight(d)
    last = FINAL_DEADLINE - timedelta(days=BUFFER_DAYS)
    problems_left = max(0, TARGET_LEETCODE - pr["done_p"])
    prob_days = weighted_days(d, last)
    per_prob = problems_left / prob_days

    topics_left = pr["tot_t"] - pr["done_t"]
    java_days = weighted_days(d, JAVA_DEADLINE) if d <= JAVA_DEADLINE else 0
    per_topic = topics_left / java_days if (java_days and topics_left) else (topics_left and 1)

    if exam_window(d):   # DSA + Java postponed; plan is college subjects only
        sw = study_weight(d)
        return dict(weight=sw, topics=0, problems=0, minutes=int(DAILY_TARGET_MINUTES * sw),
                    behind=False, exam_mode=True)
    if w == 0:
        return dict(weight=0, topics=0, problems=0, minutes=0, behind=False)
    # while Java is being finished, DSA pace is gentler (but never zero)
    problems = math.ceil(per_prob * w * (0.6 if topics_left and d <= JAVA_DEADLINE else 1))
    topics = math.ceil(per_topic * w) if topics_left else 0
    return dict(weight=w, topics=min(topics, topics_left), problems=min(max(problems, 1 if w >= 0.3 else 0), 8),
                minutes=int(DAILY_TARGET_MINUTES * w),
                behind=problems_left > 0 and per_prob > 4)


def minutes_today() -> int:
    r = db.q("SELECT COALESCE(SUM(minutes),0) m FROM study_log WHERE day=?", (today().isoformat(),))
    return int(r[0]["m"])


def log_minutes(m: int, source="auto"):
    db.x("INSERT INTO study_log(day,minutes,source) VALUES(?,?,?)", (today().isoformat(), m, source))


def streak() -> int:
    s, d = 0, today()
    while db.q("SELECT 1 FROM study_log WHERE day=? GROUP BY day HAVING SUM(minutes)>=30", (d.isoformat(),)):
        s += 1
        d -= timedelta(days=1)
    return s


def add_event(kind, title, start: str, end: str):
    db.x("INSERT INTO events(kind,title,start,end) VALUES(?,?,?,?)", (kind, title, start, end))


def mark_problem(pid: int):
    db.x("UPDATE problems SET done=1, done_on=? WHERE id=?", (today().isoformat(), pid))


def mark_topic(tid: int):
    db.x("UPDATE topics SET done=1 WHERE id=?", (tid,))


def status_text() -> str:
    pr, q = progress(), quota()
    last = FINAL_DEADLINE - timedelta(days=BUFFER_DAYS)
    return (f"📊 Progress\n"
            f"Java course: {pr['done_t']}/{pr['tot_t']} topics (deadline {JAVA_DEADLINE})\n"
            f"Problems: {pr['done_p']}/{TARGET_LEETCODE} target ({pr['tot_p']} in list)\n"
            f"Days to finish line: {(last - today()).days}\n"
            f"Streak: {streak()} days · Studied today: {minutes_today()} min\n"
            + ("📘 EXAM MODE: DSA/Java paused until your exams end.\n" if q.get("exam_mode") else
               f"Today's quota: {q['topics']} topic(s), {q['problems']} problem(s)")
            + ("\n⚠️ You're behind pace — consider longer sessions." if q.get("behind") else ""))
