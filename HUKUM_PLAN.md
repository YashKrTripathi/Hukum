# HUKUM: master plan (personal Jarvis, "like my own brother")

Status: the placement/DSA/Telegram planner is PARKED. It stays as a skill module and gets re-enabled in Phase 9.

## 0. What Hukum is
One brain on the college server, many "bodies" on your devices.
- **Brain (server):** Hermes Agent (reasoning, memory, skills, cron) + OpenRouter models. One memory shared by every device.
- **Phone body (Android app):** ears and mouth, notification reader, WhatsApp quick-reply, call screening, SMS, location, usage.
- **PC body (Windows agent):** runs coding agents, files, browser, screen, shell; works only when the PC is on.
- **Event bus:** every body sends events to the brain ("WhatsApp from Rahul", "call missed", "PC idle") and the brain sends commands back ("reply", "run this", "remind").

## 1. Hard limits (so we don't waste weeks)
| Wish | Reality on stock Android/Windows | Plan |
|---|---|---|
| Read WhatsApp messages | Notification access gives every message that triggers a notification (text, sender, group). No history, no muted/hidden chats. | Notification listener (Phase 3) |
| Reply on WhatsApp | The notification "Reply" action (RemoteInput) works with no ban risk. Not possible if there is no notification. | Quick-reply (Phase 3) |
| Archived chat forgotten | Archived chats only notify if not muted and "keep archived" is off. | Brain keeps an "unread/unanswered" ledger from notifications and nags (Phase 4) |
| Pick up calls, caller hears Hukum | Android blocks injecting audio into a normal call. Free options: reject + SMS; speaker trick. Real answer needs VoIP forwarding (paid). | Phase 6, optional |
| Read screen / control any app | AccessibilityService can, but is fragile and sensitive. | Phase 8, opt-in only |
| Always running | Android kills background apps. | Foreground service + battery exemption + server push (Phase 1) |

## 2. Architecture
```
 Phone app ──events/commands (WebSocket)──► Hukum Gateway (college server, HTTPS) ──► Hermes (brain)
 PC agent  ──events/commands (WebSocket)──►        │                                   │ MCP tools
                                                   ├─ Postgres/SQLite: memory, ledger, contacts, tasks
                                                   ├─ OpenRouter (fast model for chat, strong model for hard jobs)
                                                   └─ Scheduler (reminders, briefings, follow-ups)
```
Rules:
- Gateway is a persistent service (systemd), not per-message processes. Hermes is called through its long-running `hermes serve` API or ACP, so replies take 2-4 s, not 10+.
- Fast path: small model answers chat and simple commands. Brain path: Hermes handles planning, memory, long tasks, coding agents.
- Every action goes through a **permission tier** (below).
- Auth: device keys + HTTPS (Caddy/Let's Encrypt). No open ports without a key.

### Permission tiers
1. **Auto:** read, remind, summarize, search, open apps.
2. **Confirm by voice or tap:** send a message, call someone, run shell commands, spend money.
3. **Never without you at the keyboard:** delete data, payments, changing credentials.

## 3. Phases

### Phase 0: Reset and foundation (2-3 days)
- Park old planner behind a feature flag. Keep the Android app, MCP bridge, events channel.
- New repo layout: `gateway/`, `brain/`, `android/`, `pc-agent/`, `skills/`.
- Deploy the gateway on the college server: systemd, HTTPS, device keys.
- Hermes on the server with Nous or OpenRouter model, hukum MCP tools registered.
- Done when: the phone app talks to the college server over HTTPS with no PC involved.

### Phase 1: Real Jarvis conversation (1 week)
- Persistent Hermes session (`serve`/ACP) for 2-4 s replies; streaming text and sentence-by-sentence TTS.
- Voice loop: tap or wake word, speak, interrupt anytime, hands-free mode.
- Wake word on device ("Hukum") using an offline engine (openWakeWord/Porcupine free tier).
- Memory v1: facts, people, preferences, routines, saved by Hermes memory plus our `remember` tool.
- Persona: brother tone, Hinglish, short answers, proactive but not annoying.
- Done when: you can talk for 5 minutes naturally and it remembers yesterday.

### Phase 2: Always-on phone body (1 week)
- Foreground service, boot start, battery exemption, reconnecting WebSocket, FCM/ntfy fallback wake.
- Phone state: battery, charging, location (coarse), Wi-Fi, do-not-disturb, screen on/off.
- Quick controls: flashlight, volume, open app, set alarm/timer, play music, navigate.
- Done when: it survives a night and reacts the next morning.

### Phase 3: Messages: read and reply (1-2 weeks)
- NotificationListenerService for WhatsApp, WhatsApp Business, SMS, Telegram, Gmail, Instagram.
- Parse sender, group, text, time; store in the server ledger.
- Commands: "kisne message kiya?", "Rahul ko bol de aa raha hu", "pichle 10 messages padh ke sunao".
- Reply via notification RemoteInput; SMS via SmsManager; confirm tier before sending.
- Smart replies: drafts in your style; auto-reply rules ("jab main busy hu").
- Done when: WhatsApp message arrives, Hukum reads it aloud and replies on your say-so.

### Phase 4: Proactive brain (1 week)
- **Unanswered ledger:** every incoming message/call is "open" until you answer it. Hukum reminds: "Boss, Rahul ne 2 ghante pehle pucha tha, abhi tak reply nahi".
- Handles the archived-chat case: it knows because it saw the notification, not the chat list.
- Missed calls: who, how many times, whether you called back.
- Daily briefing: morning (calendar, open loops, weather), evening (what slipped).
- Reminder engine: voice-set, recurring, location-based, escalating (voice, then ring, then vibrate).
- Done when: it nags about a forgotten reply without being asked.

### Phase 5: PC agent and coding agents (1-2 weeks) - FIRST VERSION BUILT: pcbridge.py + hukum_pc.py, tested end to end; needs your PC key + trial
- Windows agent (Python, service) with the same gateway protocol.
- Tools: run command, read/write files in allowed folders, open apps, screenshots, clipboard, window list.
- **Coding agents:** launch and supervise Claude Code / Hermes / Codex sessions in a repo from your phone ("hukum, hukum-android me build chalao"), stream summaries, ask you for approvals by voice, report when done.
- Idle/activity detection to know whether you are at the PC.
- Done when: you start a coding task from the phone and get "build ho gaya, 2 warnings" back.

### Phase 6: Calls (open-ended, pick one path)
- **6A free:** silent reject + SMS reply (built). Missed-call log in the ledger.
- **6B free, limited:** awake-mode speaker greeting.
- **6C real:** forward unanswered calls to a VoIP number (SIP trunk) so Hukum talks to the caller live and takes a message. Needs a paid service or an existing college PBX/Asterisk. Ask the college IT whether they run Asterisk/FreePBX: that would make it free.
- Outgoing calls on your command are already built (dial).

### Phase 7: Knowledge and tools (ongoing)
- Calendar (Google/ICS), email (read, summarize, draft), documents, notes.
- Web research, file search on the server and PC, document Q&A over your notes and college PDFs.
- Hermes skills for repeating workflows (e.g. "exam prep", "standup notes").

### Phase 8: Advanced (opt-in)
- AccessibilityService for apps with no API; screen reading on request.
- Vision: "ye kya hai" through the camera or screenshots.
- Home and device control (Home Assistant, smart plugs) if you own any.
- Multi-agent: separate Hermes profiles for coding, research, admin work.

### Phase 9: Bring back the planner
- Re-enable DSA/LeetCode/exam planning as a skill that Hukum uses; same data.

## 4. Safety, privacy, reliability
- Messages are stored on the college server only. Encrypt the disk, back it up nightly, keep a "forget this" command.
- Redact OTPs and banking messages before the model sees them (regex rules, on by default).
- Audit log of every action Hukum took; "kya kiya aaj?" returns it.
- Kill switch: one tap in the app and a spoken "Hukum stop" disables all actions.
- Rate limits and spend limits on OpenRouter; a fallback model if one is down.
- Tests: a scripted scenario suite (message arrives, call missed, command from the phone) run before each release.

## 5. Tech choices
- Gateway: Python (FastAPI or stdlib + websockets), SQLite then Postgres.
- Brain: Hermes via `serve`/ACP + OpenRouter (fast: small model; strong: Claude/GPT-class for hard tasks).
- Android: Kotlin + Compose (existing), OkHttp WebSocket, NotificationListenerService, Porcupine/openWakeWord.
- PC: Python agent as a Windows service.
- Voice: server TTS (edge-tts now; a better engine later), on-device STT first, Whisper on the server for quality.

## 6. Suggested order and effort
Phase 0 → 1 → 2 → 3 → 4 gives a working Jarvis in about 5-6 weeks. Phase 5 adds the PC and coding agents. Phase 6C waits for the college IT answer.

## 7. Open questions for you
1. Which model budget on OpenRouter per month? (sets the fast/strong split)
2. Can the college server run a persistent service with a public HTTPS name? Who is the contact?
3. Does the college run Asterisk/FreePBX or another SIP system?
4. Which apps matter most for message reading: WhatsApp, SMS, Gmail, Telegram, others?
5. Should replies to people ever go out without your OK (for example only to named contacts)?
