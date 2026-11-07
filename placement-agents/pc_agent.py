"""Runs on YOUR PC (when it's on). Sends a state label every minute to your private ntfy
topic; the cloud bot reads it. Window titles never leave your PC.
    python pc_agent.py
Auto-start: Win+R -> shell:startup -> put a shortcut to run_pc_agent.bat there."""
import time
import notify
from agents import watcher

if not notify.enabled():
    raise SystemExit("Set NTFY_TOPIC (and NTFY_SERVER) in .env first")

print("PC agent running. Ctrl+C to stop.")
while True:
    notify.publish_pc(watcher.local_sample())
    time.sleep(60)
