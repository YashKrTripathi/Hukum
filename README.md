# Hukum

A personal Jarvis: a brain on the college GPU server, with bodies on the phone and the PC.

- `placement-agents/` the gateway (Python, stdlib server): chat brain, tools, message inbox, PC job queue, plus the parked study planner.
  `hukum_pc.py` is the PC agent; `hukum_mcp.py` bridges Hermes to the tools.
- `hukum-android/` the Android app (Kotlin/Compose): voice, notification reader, call screening, replies.
- `HUKUM_PLAN.md` the master plan and phases.

## Secrets
Nothing secret lives here. `.env`, databases, Telegram sessions, APKs and `hukum_pc.json` are git-ignored and stay on the machines.
See `placement-agents/.env.example`.

## Deploy (pull-based, safe for a public repo)
On the CRM server, once:
```
git clone https://github.com/YashKrTripathi/Hukum.git ~/hukum-repo && bash ~/hukum-repo/deploy/setup-hukum-crm.sh
```
After that every push to `main` goes live within 1-2 minutes: the server checks GitHub every minute, runs the tests, backs up,
copies the code, restarts, health-checks and rolls back automatically on failure. Log: `<gateway folder>/deploy.log`.
No self-hosted runner is used on purpose: with a public repository a pull request could otherwise run code on the server.

## Tests
`cd placement-agents && python -m unittest tests.test_pc -v` (gateway + PC agent end to end, no LLM needed). CI runs it on GitHub.
