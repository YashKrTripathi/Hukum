"""Hukum Desktop - run this to start the assistant and its dashboard.
    python hukum_desktop.py            start and open the dashboard
    python hukum_desktop.py --no-browser --port 8790
"""
import argparse
import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    from core import store, sysmon, projects, agents, automation, gateway, server, notify, permissions, autostart
    store.init()
    store.purge()
    sysmon.start()
    projects.scan_loop()
    agents.start()
    automation.start()
    gateway.start(server.execute_job)
    srv = server.make(a.port)
    url = f"http://127.0.0.1:{a.port}/?t={srv.token}"
    store.audit("system", "start", url.split("?")[0])
    print("Hukum Desktop is running.")
    print("Dashboard:", url)
    print("(the link contains your private access token - do not share it)")

    def on_setting(key, value):
        try:
            if key == "system.autostart":
                autostart.set_enabled(bool(value))
            elif key == "system.tray":
                autostart.start_tray(a.port, srv.token) if value else autostart.stop_tray()
        except Exception as e:
            print("setting", key, "failed:", e)
    store.on_change(on_setting)
    if store.get("system.autostart") != autostart.is_enabled():
        store.set_("system.autostart", autostart.is_enabled())          # show the real state
    if store.get("system.tray"):
        autostart.start_tray(a.port, srv.token)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    def housekeeping():
        while True:
            time.sleep(3600)
            try:
                store.purge()
            except Exception:
                pass
    threading.Thread(target=housekeeping, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
