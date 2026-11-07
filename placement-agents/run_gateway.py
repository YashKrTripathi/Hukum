"""Hukum gateway: runs on the CRM server (no Telegram, no PC-only agents).
Serves the app API (/api/chat, /api/events, /api/tool, /api/tts ...) and talks to the GPU brain
through LLM_BASE_URL. Behind nginx:  https://crm.dypiu.ac.in/hukum/  ->  127.0.0.1:8765"""
import os
import time
import db
import seed
import threading
import webserver
import inbox
import chat_agent

db.init()
seed.run()
port = webserver.start()
pub = os.getenv("WEB_PUBLIC_URL", "").rstrip("/")
if pub:
    db.put("web_url", pub)
print(f"Hukum gateway on {os.getenv('WEB_HOST', '0.0.0.0')}:{port}")
print("App link:", webserver.link() or "(set WEB_PUBLIC_URL in .env)")
threading.Thread(target=inbox.nudge_loop, args=(webserver.push_event, chat_agent.spoken), daemon=True).start()
while True:
    time.sleep(3600)
