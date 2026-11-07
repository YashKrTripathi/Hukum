"""Orchestrator + Reminder agent. Run:  python bot.py
Agents: Reminder (this file, morning ask + escalation) · Tracker · Suggester · Watcher · Caller
"""
import asyncio
import os
import queue
import re
import tempfile
import time
from zoneinfo import ZoneInfo
from datetime import datetime, date, timedelta, time as dtime
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)
import db
import seed
from config import (BOT_TOKEN, MORNING_TIME, DEFAULT_STUDY_TIME, DAILY_TARGET_MINUTES,
                    TZ_NAME)
import llm
import voice
import chat_agent
import webserver
import tunnel
from agents import tracker, suggester, watcher, caller
import notify
import lc_sync

ACK_BTNS = [("▶️ Starting now", "ack"), ("🙅 Busy +1h", "later1"), ("Busy +2h", "later2")]

HELP = """Commands:
/today – today's plan        /status – progress
/done P12 T3 S4 – mark problems / Java topics / college units done
/syllabus DBMS | Unit 1; Unit 2; Unit 3 – save syllabus for a subject
/sync – pull LeetCode progress now
/studying cloud arch 90 – I'm studying that subject for 90 min (focus mode)
/practical 2026-11-21 2026-11-28 Practicals – practical exams (3-day prep window)
/events, /delevent 3 – see or remove calendar entries
/talk – link to the live voice page (install it as an app)
/topics – next course topics   /unlock all – ignore course order for problems
Send a .csv/.txt file of problems to import them into your list
/log 45 – log 45 manual study minutes
/busy – I can't study now (I'll ask when)
/exam 2026-12-01 2026-12-10 Mid-sem
/vacation 2026-12-20 2027-01-05 Winter
/call – test the phone-call escalation"""


TZ = ZoneInfo(TZ_NAME)


def hm(s):  # "HH:MM" -> timezone-aware time (PTB would otherwise assume UTC)
    h, m = s.split(":")
    return dtime(int(h), int(m), tzinfo=TZ)


async def exam_pdf(u: Update, ctx):
    """Send your exam timetable PDF to the bot."""
    import json
    import exam_import
    if not llm.available():
        await u.message.reply_text("Set OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) in .env first.")
        return
    await u.message.reply_text("📄 Reading your timetable…")
    f = await u.message.document.get_file()
    path = os.path.join(tempfile.gettempdir(), "timetable.pdf")
    await f.download_to_drive(path)
    try:
        exams = await asyncio.to_thread(exam_import.extract, path)
    except Exception as e:
        await u.message.reply_text(f"Couldn't parse it ({e}). Add exams manually with /exam.")
        return
    db.put("pending_exams", json.dumps(exams))
    lines = "\n".join(f"{e['date']}  {e['subject']} {e.get('time', '')}" for e in exams)
    await u.message.reply_text(f"I found:\n{lines}\n\nSave these?",
                               reply_markup=M([[B("✅ Save", callback_data="exam_save"),
                                                B("❌ Cancel", callback_data="exam_cancel")]]))


async def say(ctx, text, kb=None, push=False, urgent=False, buttons=None):
    """Telegram always; also phone-app push (ntfy) when push/urgent."""
    chat = db.get("chat_id")
    if chat:
        await ctx.bot.send_message(int(chat), text, reply_markup=kb)
    if push or urgent:
        await asyncio.to_thread(notify.push, text[:300], "Placement Agent",
                                5 if urgent else 4, buttons, ["rotating_light"] if urgent else None,
                                webserver.link())


async def do_call(ctx, reason):
    webserver.push_event("ring", reason)    # rings the Hukum Android app (full-screen call)
    await asyncio.to_thread(notify.push, f"📞 STUDY CALL: {reason}", "📞 STUDY NOW", 5, ACK_BTNS,
                            ["telephone_receiver", "rotating_light"], webserver.link())
    ok = False
    try:
        ok = await caller.ring(reason)
    except Exception as e:
        print("call failed:", e)
    await send_voice(ctx, reason)       # the "call" speaks to you right after it rings
    if not ok and not notify.enabled():  # fallback: loud repeated messages
        await say(ctx, f"📞🔔 CALL (fallback) — {reason}")
        await say(ctx, "🔔 ANSWER ME. Open your laptop and start.")


# ---------- commands ----------
async def start(u: Update, ctx):
    db.put("chat_id", u.effective_chat.id)
    await u.message.reply_text("✅ Linked. I'll plan, remind and call you.\n\n" + HELP)


async def today_cmd(u, ctx):
    await u.message.reply_text(suggester.plan_text())


async def status_cmd(u, ctx):
    await u.message.reply_text(tracker.status_text())


async def done_cmd(u, ctx):
    out = []
    for a in ctx.args:
        m = re.fullmatch(r"([PpTtSs])(\d+)", a)
        if not m:
            continue
        k = m[1].lower()
        if k == "s":
            db.x("UPDATE syllabus SET done=1 WHERE id=?", (int(m[2]),))
        else:
            (tracker.mark_problem if k == "p" else tracker.mark_topic)(int(m[2]))
        out.append(a.upper())
    await u.message.reply_text(("✅ Marked " + ", ".join(out) + "\n\n" + tracker.status_text()) if out
                               else "Usage: /done P12 T3")


async def log_cmd(u, ctx):
    try:
        tracker.log_minutes(int(ctx.args[0]), "manual")
        db.put("acked", date.today().isoformat())
        await u.message.reply_text(f"Logged. Today: {tracker.minutes_today()} min")
    except Exception:
        await u.message.reply_text("Usage: /log 45")


async def event_cmd(u, ctx, kind):
    try:
        s, e = ctx.args[0], ctx.args[1]
        date.fromisoformat(s), date.fromisoformat(e)
        tracker.add_event(kind, " ".join(ctx.args[2:]) or kind, s, e)
        q = tracker.quota()
        await u.message.reply_text(f"Saved {kind} {s}→{e}. I'll rebalance the plan.\n"
                                   f"Today's quota now: {q['problems']} problems, {q['topics']} topics.")
    except Exception:
        await u.message.reply_text(f"Usage: /{kind} YYYY-MM-DD YYYY-MM-DD name")


async def syllabus_cmd(u, ctx):
    try:
        subj, units = u.message.text.split(None, 1)[1].split("|", 1)
        subj = subj.strip()
        canon = tracker.resolve_subject(subj)
        if not canon:
            names = "\n".join(f"• {t}" for t, _, _ in tracker.exam_subjects())
            await u.message.reply_text("Which subject? Use words that match exactly one exam:\n" + names)
            return
        subj = canon
        us = [x.strip() for x in units.split(";") if x.strip()]
        for x_ in us:
            db.x("INSERT OR IGNORE INTO syllabus(subject,unit) VALUES(?,?)", (subj, x_))
        await u.message.reply_text(f"Saved {len(us)} units for {subj}.")
    except Exception:
        await u.message.reply_text("Usage: /syllabus DBMS | Unit 1 ER model; Unit 2 SQL; Unit 3 Normalization\n"
                                   "Subject name must match the exam name from your timetable.")


async def practical_cmd(u, ctx): await event_cmd(u, ctx, "practical")


async def events_cmd(u, ctx):
    rows = db.q("SELECT * FROM events ORDER BY start")
    await u.message.reply_text("📅 Calendar:\n" + "\n".join(
        f"#{r['id']} {r['kind']}: {r['title']} {r['start']}→{r['end']}" for r in rows)
        + "\n\nRemove one: /delevent <id>" if rows else "No events yet.")


async def delevent_cmd(u, ctx):
    try:
        db.x("DELETE FROM events WHERE id=?", (int(ctx.args[0]),))
        await u.message.reply_text("Removed.\n\n" + suggester.plan_text())
    except Exception:
        await u.message.reply_text("Usage: /delevent <id>  (see /events)")


async def unlock_cmd(u, ctx):
    off = bool(ctx.args) and ctx.args[0].lower() == "all"
    db.put("gate_off", 1 if off else 0)
    await u.message.reply_text("🔓 Problems no longer wait for course topics." if off
                               else "🔒 Problems unlock as you finish course topics.")


async def import_doc(u: Update, ctx):
    """Send a .csv/.txt of problems (topic,name or 'Arrays:' headers + names)."""
    f = await u.message.document.get_file()
    path = os.path.join(tempfile.gettempdir(), "problems_import.txt")
    await f.download_to_drive(path)
    with open(path, encoding="utf-8-sig", errors="ignore") as fh:
        added, total = seed.import_text(fh.read())
    await u.message.reply_text(f"📥 Added {added} new problems. {total} in your list now.")


async def talk_cmd(u, ctx):
    link = webserver.link()
    await u.message.reply_text(
        f"🎙 Talk to me live:\n{link}\n\nOpen it on your phone in Chrome, then Menu → Add to Home screen "
        f"to install it as an app." if link else
        "The voice page has no public address yet. Install cloudflared "
        "(winget install Cloudflare.cloudflared) and restart the bot, or set WEB_PUBLIC_URL in .env.")


async def topics_cmd(u, ctx):
    rows = db.q("SELECT id,name FROM topics WHERE done=0 ORDER BY ord LIMIT 12")
    await u.message.reply_text("☕ Next course topics:\n" + "\n".join(f"T{r['id']}. {r['name']}" for r in rows)
                               if rows else "🎉 Course finished!")


async def studying_cmd(u, ctx):
    """/studying cloud arch 90  -> focus mode: counts as study, no nagging, for 90 min."""
    args = list(ctx.args)
    mins = int(args.pop()) if args and args[-1].isdigit() else 60
    subj = tracker.resolve_subject(" ".join(args)) if args else None
    if args and not subj:
        names = "\n".join(f"• {t}" for t, _, _ in tracker.exam_subjects())
        await u.message.reply_text("Which subject? Use words matching exactly one:\n" + names)
        return
    db.put("focus_until", time.time() + mins * 60)
    db.put("acked", date.today().isoformat())
    db.put("bad", 0)
    if mins == 0:
        await u.message.reply_text("Focus mode off.")
        return
    await u.message.reply_text(f"📘 Focus: {subj or 'study'} for {mins} min. I won't nag and it counts as study. "
                               f"Mark units with /done S<n>.")


async def sync_now(ctx):
    try:
        found = await asyncio.to_thread(lc_sync.sync)
    except Exception as e:
        print("LeetCode sync failed:", e)
        return
    if found:
        await say(ctx, "✅ Detected on LeetCode: " + ", ".join(found))


async def sync_cmd(u, ctx):
    await sync_now(ctx)
    await u.message.reply_text(tracker.status_text())


async def drain_replies(ctx):
    """Button taps coming back from the phone app."""
    while True:
        try:
            r = notify.REPLIES.get_nowait()
        except queue.Empty:
            return
        if r == "ack":
            db.put("acked", date.today().isoformat()); db.put("bad", 0)
            await say(ctx, "🔥 Good. Timer running. I'm watching 👀")
        elif r in ("later1", "later2"):
            t = (datetime.now() + timedelta(hours=1 if r == "later1" else 2)).strftime("%H:%M")
            db.put("study_time", t); db.put("acked", ""); db.put("stage", 0)
            await say(ctx, f"⏰ Okay, next reminder at {t}.")
        elif r == "ci_study":
            tracker.log_minutes(30, "manual"); db.put("other", 0)
        elif r == "ci_waste":
            await do_call(ctx, "You said you're wasting time. Study now.")


async def exam_cmd(u, ctx): await event_cmd(u, ctx, "exam")
async def vac_cmd(u, ctx): await event_cmd(u, ctx, "vacation")


async def busy_cmd(u, ctx):
    db.put("awaiting_time", 1)
    await u.message.reply_text("Okay. When can you study today? Reply with a time like 21:30")


async def call_cmd(u, ctx):
    await u.message.reply_text("Ringing you…")
    await do_call(ctx, "test call")


async def send_voice(ctx, text):
    """Speak `text` to you as a Telegram voice message."""
    try:
        chat = db.get("chat_id")
        if not chat:
            return
        path = os.path.join(tempfile.gettempdir(), f"hukum_{int(time.time())}.mp3")
        await voice.speak(await asyncio.to_thread(chat_agent.spoken, text), path)
        with open(path, "rb") as f:
            await ctx.bot.send_voice(int(chat), f)
        os.remove(path)
    except Exception as e:
        print("voice reply failed:", e)


async def agent_reply(u: Update, ctx, text, with_voice):
    if not llm.available():
        await u.message.reply_text("Set LLM_BASE_URL (own server) or OPENROUTER_API_KEY in .env so I can chat with you.")
        return
    await ctx.bot.send_chat_action(u.effective_chat.id, "typing")
    try:
        reply = await asyncio.to_thread(chat_agent.respond, text)
    except Exception as e:
        await u.message.reply_text(f"⚠️ Brain error: {e}")
        return
    await u.message.reply_text(reply)
    if with_voice:
        await send_voice(ctx, reply)


async def voice_msg(u: Update, ctx):
    """You send a voice note (Hinglish/Hindi/English); I answer in text and voice."""
    if not voice.stt_available():
        await u.message.reply_text("Set GROQ_API_KEY (free, console.groq.com) in .env to understand voice notes.")
        return
    m = u.message.voice or u.message.audio
    f = await m.get_file()
    path = os.path.join(tempfile.gettempdir(), "hukum_in.ogg")
    await f.download_to_drive(path)
    try:
        text = await voice.transcribe(path)
    except Exception as e:
        await u.message.reply_text(f"Couldn't understand the audio: {e}")
        return
    await u.message.reply_text(f"🎙 {text}")
    await agent_reply(u, ctx, text, with_voice=True)


async def text_reply(u: Update, ctx):
    if db.get("awaiting_time") != "1":
        await agent_reply(u, ctx, u.message.text, with_voice=False)
        return
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", u.message.text)
    if not m:
        await agent_reply(u, ctx, u.message.text, with_voice=False)
        return
    t = f"{int(m[1]):02d}:{m[2]}"
    if t <= datetime.now().strftime("%H:%M"):
        await u.message.reply_text("That time already passed. Send a later one, or /log to record study.")
        return
    db.put("study_time", t)
    db.put("awaiting_time", 0)
    db.put("acked", "")
    db.put("stage", 0)
    await u.message.reply_text(f"⏰ Locked: {t}. I'll come looking for you then.")


async def buttons(u: Update, ctx):
    q = u.callback_query
    await q.answer()
    d = q.data
    if d == "ack":
        db.put("acked", date.today().isoformat())
        db.put("bad", 0)
        await q.edit_message_text("🔥 Good. Timer running. I'm watching 👀")
    elif d == "exam_save":
        import json
        for e in json.loads(db.get("pending_exams", "[]")):
            tracker.add_event("exam", e["subject"], e["date"], e["date"])
        db.put("pending_exams", "[]")
        await q.edit_message_text("✅ Exams saved. Now add syllabus: /syllabus <subject> | unit1; unit2")
    elif d == "exam_cancel":
        db.put("pending_exams", "[]")
        await q.edit_message_text("Cancelled.")
    elif d == "busy":
        db.put("awaiting_time", 1)
        await q.edit_message_text("When then? Reply with a time like 21:30")
    elif d == "ci_study":
        tracker.log_minutes(30, "manual"); db.put("other", 0)
        await q.edit_message_text("Logged 30 min. Keep going.")
    elif d == "ci_rest":
        db.put("other", 0)
        await q.edit_message_text("Fine, short break. Back in 15 min.")
    elif d == "ci_waste":
        await q.edit_message_text("Honest answer. Close it and open your IDE now.")
        await do_call(ctx, "You said you're wasting time. Study now.")


# ---------- scheduled jobs ----------
async def morning(ctx: ContextTypes.DEFAULT_TYPE):
    q = tracker.quota()
    if q["weight"] == 0:
        await say(ctx, "🌤 No study today. Enjoy your day.")
        return
    coach = suggester.coach_line(f"streak {tracker.streak()} days; today needs {q['problems']} problems, {q['topics']} Java topics")
    db.put("awaiting_time", 1)
    await say(ctx, f"☀️ Good morning!\n{coach}\n\n{suggester.plan_text()}\n\n"
                   f"⏰ When will you study today? Reply a time (e.g. 18:30). Default {db.get('study_time')}.")


async def evening_report(ctx):
    await say(ctx, "🌙 Day summary\n" + tracker.status_text())


def reset_day():
    t = date.today().isoformat()
    if db.get("state_day") != t:
        for k, v in dict(state_day=t, acked="", stage=0, bad=0, other=0, last_action=0,
                         nudges=0, awaiting_time=0, study_time=DEFAULT_STUDY_TIME).items():
            db.put(k, v)


async def tick(ctx: ContextTypes.DEFAULT_TYPE):
    """Every minute: log study, detect wasted time, escalate reminders."""
    if not db.get("chat_id"):
        return
    reset_day()
    today = date.today().isoformat()
    s = watcher.sample()
    if float(db.get("focus_until", 0)) > time.time():
        s = "study"            # you told me you're studying (e.g. a college subject)
    if s == "study":
        tracker.log_minutes(1, "auto")
        if db.get("acked") != today:
            db.put("acked", today)

    w = tracker.study_weight(date.today())
    if w == 0:
        return
    now = datetime.now()
    if now.strftime("%H:%M") < db.get("study_time"):
        return
    if tracker.minutes_today() >= DAILY_TARGET_MINUTES * w:
        return
    if now.hour >= 23:
        return

    ts = time.time()
    last = float(db.get("last_action", 0))
    stage = int(db.get("stage", 0))

    if db.get("acked") != today:
        # Reminder escalation: message -> call after 10 min -> call every 20 min
        gap = 0 if stage == 0 else (10 * 60 if stage == 1 else 20 * 60)
        if ts - last >= gap and stage < 6:
            reason = suggester.coach_line("It is study time and the student hasn't started")
            if stage == 0:
                await say(ctx, f"⏰ Study time! {reason}\n\n{suggester.plan_text()}",
                          M([[B("▶️ Starting now", callback_data="ack"),
                              B("🙅 Busy", callback_data="busy")]]),
                          push=True, buttons=ACK_BTNS)
            else:
                await say(ctx, f"📞 Calling you — {reason}",
                          M([[B("▶️ Starting now", callback_data="ack"),
                              B("🙅 Busy", callback_data="busy")]]))
                await do_call(ctx, reason)
            db.put("stage", stage + 1)
            db.put("last_action", ts)
        return

    # Acked but wasting time?
    bad = int(db.get("bad", 0))
    other = int(db.get("other", 0))
    if s in ("distract", "idle"):
        bad += 1
        db.put("bad", bad)
    elif s == "study":
        db.put("bad", 0); db.put("other", 0)
    else:
        db.put("other", other + 1)
        if other + 1 >= 30:  # can't tell what you're doing
            db.put("other", 0)
            await say(ctx, "🤔 What are you doing right now?",
                      M([[B("📚 Studying", callback_data="ci_study"),
                          B("😴 Resting", callback_data="ci_rest"),
                          B("🙈 Wasting time", callback_data="ci_waste")]]),
                      push=True, buttons=[("📚 Studying", "ci_study"), ("🙈 Wasting time", "ci_waste")])
    if bad >= 10:
        db.put("bad", 0)
        n = int(db.get("nudges", 0)) + 1
        db.put("nudges", n)
        await say(ctx, f"👀 You've been on '{watcher.active_title()[:40] or 'nothing'}' / idle for 10 min. Open your IDE.")
        if n >= 2:
            db.put("nudges", 0)
            await do_call(ctx, "Caught you wasting time. Start studying.")


def main():
    if not BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (copy .env.example)")
    db.init()
    seed.run()
    app = Application.builder().token(BOT_TOKEN).build()
    for name, fn in [("start", start), ("help", start), ("today", today_cmd), ("status", status_cmd),
                     ("done", done_cmd), ("log", log_cmd), ("busy", busy_cmd),
                     ("exam", exam_cmd), ("vacation", vac_cmd), ("call", call_cmd),
                     ("syllabus", syllabus_cmd), ("sync", sync_cmd), ("studying", studying_cmd),
                     ("topics", topics_cmd), ("practical", practical_cmd), ("events", events_cmd),
                     ("delevent", delevent_cmd), ("unlock", unlock_cmd), ("talk", talk_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.Document.PDF, exam_pdf))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv") | filters.Document.FileExtension("txt"),
                                   import_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_reply))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_msg))
    jq = app.job_queue
    jq.run_daily(morning, hm(MORNING_TIME))
    jq.run_daily(evening_report, dtime(22, 30, tzinfo=TZ))
    jq.run_repeating(tick, interval=60, first=10)
    jq.run_repeating(drain_replies, interval=3, first=5)
    jq.run_repeating(sync_now, interval=900, first=30)
    notify.start_listener(watch_pc=os.getenv("WATCHER_SOURCE", "local") == "remote")
    port = webserver.start()
    fixed = os.getenv("WEB_PUBLIC_URL", "").rstrip("/")

    def got_url(u_):
        db.put("web_url", u_)
        print("Voice page:", webserver.link())
        notify.push("Voice page is ready. Tap to talk with Hukum.", "🎙 Talk to Hukum", 3, None, None,
                    webserver.link())

    if fixed:
        got_url(fixed)
    elif not tunnel.start(port, got_url):
        db.put("web_url", "")
    print(f"Voice page on http://localhost:{port}  (link appears below once the tunnel is up)")
    print("Placement agents running. Message your bot /start on Telegram.")
    asyncio.set_event_loop(asyncio.new_event_loop())  # Python 3.14+ no longer creates one
    app.run_polling()


if __name__ == "__main__":
    main()
