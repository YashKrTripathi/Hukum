"""Gives the voice page a public https address (needed for the phone's microphone) using a
Cloudflare quick tunnel. Needs the free `cloudflared` program:  winget install Cloudflare.cloudflared
The address changes each time the bot starts; the bot sends you the new link automatically.
Alternative: set WEB_PUBLIC_URL in .env to a fixed https address (named tunnel, Tailscale Funnel...)."""
import re
import shutil
import subprocess
import threading


def start(port: int, on_url) -> bool:
    exe = shutil.which("cloudflared")
    if not exe:
        print("cloudflared not found. Install: winget install Cloudflare.cloudflared "
              "(or set WEB_PUBLIC_URL in .env). Voice page will only work on this PC for now.")
        return False

    def run():
        p = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="ignore")
        for line in p.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m:
                on_url(m.group(0))

    threading.Thread(target=run, daemon=True).start()
    return True
