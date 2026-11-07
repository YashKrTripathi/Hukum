# Hukum Desktop

Hukum's PC half: a local assistant that sees the apps you approve, controls Windows through verified actions, runs coding
agents, talks to your phone and shows everything on a local dashboard. Standard-library Python plus PowerShell 5.1 (UI
Automation and Windows OCR). No pip installs.

```
python hukum_desktop.py            # starts everything, opens the dashboard
python hukum_desktop.py --port 8790 --no-browser
```

The console prints a dashboard link containing a private access token (also stored in `data/token.txt`). The server listens
on 127.0.0.1 only, rejects other Host/Origin headers and needs the token on every request.

## What is real (and how it is checked)

| Area | Behaviour |
|---|---|
| Apps | launch / focus / close for Antigravity, Claude, Codex, VS Code, Chrome, Edge, terminals, Explorer, Task Manager, Notepad. Launch waits for a new window; focus is verified against the foreground window; close sends WM_CLOSE and reports "save?" dialogs instead of force-killing |
| UI control | type (SendInput), key combos, press a named control (UI Automation Invoke, mouse fallback), read window text |
| Screen | per-window capture (PrintWindow), local OCR (Windows.Media.Ocr), secrets redacted; private windows and excluded apps are never captured |
| Monitoring | opt-in worker over approved apps: UIA text first, OCR if empty, skips unchanged windows, finds *new* lines only, 16 detectors (build/test failures, busy ports, crashed servers, agent waiting/finished/errored, browser error pages, ...). Every finding says what was **observed** and what is **inferred** |
| Projects | git/stack/scripts/ports scan, env key *names* only, running dev servers by listening port |
| Agents | Codex (`codex exec`), Antigravity (`agy -p`), Claude desktop (window automation). Job queue, dependencies, one writer per repo, cancel, timeout, verification command, changed-file list |
| Messages | WhatsApp through the phone: replies via the Hukum gateway, new chats via adb deep link, Send button verified on screen; every send is shown for approval |
| Memory / tasks | facts, preferences, decisions; tasks with due dates, priorities, dependencies |
| Automation | schedule / interval / event / app triggers, conditions, retries, run history, pause |
| Voice | microphone and speech in the dashboard (browser Web Speech), optional wake word |
| Safety | every action is risk-rated (low/medium/high/critical), per-category switches, approval queue (critical needs the word CONFIRM), emergency stop, audit log with secrets redacted |

## Layout
`core/` modules (store/settings, permissions, winapi, pshost, uia, screen, apps, monitor, projects, agents, whatsapp, tools,
commander, automation, notify, ai, memory, gateway, server) · `ui/` dashboard · `tests/` (`test_core` portable, `test_live`
drives a real Windows desktop; skipped elsewhere or with `HUKUM_LIVE=0`) · `data/` local database (git-ignored).

## Settings and secrets
Everything is in Settings in the dashboard (the list comes from `core/store.py:SETTINGS`, so a control exists only if code reads it).
API keys and gateway keys are kept in Windows Credential Manager, never in files or logs.

## Phone → PC jobs
Turn on *Settings > Communication > gateway.link* with the gateway PC key. Jobs from the phone (open, read, run, code, stop,
command) run through the same permission manager; the phone's approval counts for low/medium/high risk, critical is refused.

## Phone app (Hukum Android 2.0)
The app's PC tabs (PC, Agents, Tasks, Alerts, More) call this dashboard's API through the gateway: phone -> `POST /api/desktop` ->
PC job channel (`kind: api`) -> `server.relay()`. Only an allow-list of endpoints is reachable (never Settings, never quit). The
phone's own confirm dialog counts as approval for low/medium/high actions; critical actions are refused and can only be approved
at the PC. Needs *gateway.link* on and the PC key set.

## Tests
```
python -m unittest tests.test_core          # anywhere
python -m unittest tests.test_live          # on the Windows PC (opens and closes its own Notepad window)
python -m unittest tests.test_phone_relay   # phone -> gateway -> desktop data path (Windows, needs ../placement-agents)
```
