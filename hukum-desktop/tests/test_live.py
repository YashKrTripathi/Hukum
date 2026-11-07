"""Live tests on a real Windows desktop: they start the dashboard server in-process, then drive it over HTTP exactly like the
UI does. They only touch windows they open themselves (a fresh Notepad) and never close anything else.
Skipped off Windows or with HUKUM_LIVE=0."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

LIVE = sys.platform == "win32" and os.environ.get("HUKUM_LIVE", "1") != "0"
_tmp = tempfile.mkdtemp(prefix="hukum_live_")
os.environ["HUKUM_DATA"] = _tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if LIVE:
    from core import store, server, winapi, permissions, agents, projects, monitor, screen, uia
    store.init()
    store.set_("folders.allowed", os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "," + _tmp)
    store.set_("confirm.medium", "auto")


@unittest.skipUnless(LIVE, "needs a Windows desktop")
class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.make(0)
        cls.port = cls.srv.server_address[1]
        cls.tok = cls.srv.token
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.hw = None

    @classmethod
    def tearDownClass(cls):
        if cls.hw and winapi.is_window(cls.hw):
            winapi.close_window(cls.hw)
            time.sleep(1)
            for d in uia.dialogs():
                if "Notepad" in d["title"] or "Save" in d["title"]:
                    try:
                        uia.press(d["hwnd"], name="Don't Save")
                    except Exception:
                        pass
        cls.srv.shutdown()

    def api(self, path, body=None, token=True, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["X-Token"] = self.tok
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{path}", None if body is None else json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"_http": e.code, **(json.loads(e.read() or b"{}"))}

    def tool(self, _tool, **args):
        return self.api("tools/call", {"name": _tool, "args": args})

    # ---- security of the server itself
    def test_01_auth(self):
        self.assertEqual(self.api("overview", token=False)["_http"], 401)
        self.assertEqual(self.api("overview", headers={"Origin": "http://evil.example"})["_http"], 401)
        self.assertTrue(self.api("ping")["ok"])

    def test_02_every_get_endpoint(self):
        for ep in ("overview", "monitor", "apps", "windows", "projects", "agents", "tasks", "memory", "notifications", "activity", "audit", "approvals",
                   "workflows", "system", "integrations", "settings", "tools", "chat/history", "servers"):
            r = self.api(ep)
            self.assertNotIn("_http", r if isinstance(r, dict) else {}, ep)

    # ---- the real desktop
    def test_03_launch_type_read_ocr_close(self):
        before = {w["hwnd"] for w in winapi.list_windows()}
        r = self.tool("app_launch", name="notepad")
        self.assertTrue(r["ok"], r)
        new = [w for w in winapi.list_windows() if w["hwnd"] not in before and w["name"].lower() == "notepad"]
        self.assertTrue(new, "a new Notepad window must exist (launch is verified)")
        type(self).hw = new[0]["hwnd"]
        r = self.tool("ui_type", app="notepad", hwnd=self.hw, text="Hukum live test 12345")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["result"]["verified"])
        r = self.tool("ui_read", hwnd=self.hw)
        self.assertIn("Hukum live test 12345", r["result"]["text"])
        r = self.tool("screen_read", hwnd=self.hw)
        self.assertTrue(r["ok"], r)
        self.assertIn("Hukum", r["result"]["text"])                      # local OCR really read the pixels
        # the monitor reads the same window and reports only new lines
        w = winapi.window_info(self.hw)
        monitor._win.clear()
        a = monitor.observe(w)
        self.assertTrue(any("Hukum live test" in ln for ln in a["new_lines"]))
        self.assertTrue(monitor.observe(w).get("unchanged"))
        # close: Notepad asks to save -> reported, not force-killed
        res = {}
        th = threading.Thread(target=lambda: res.update(r=self.tool("app_close", hwnd=self.hw)), daemon=True)
        th.start()
        for _ in range(60):                                          # closing is high risk: it must wait for Boss
            if self.api("approvals")["pending"]:
                break
            time.sleep(0.2)
        self.assertTrue(winapi.is_window(self.hw), "must not close before approval")
        self.api("approvals/decide", {"id": self.api("approvals")["pending"][0]["id"], "decision": "approve"})
        th.join(40)
        r = res["r"]
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["remaining"], 1)
        self.assertIn("asking", r["result"]["note"])
        for d in uia.dialogs(w["pid"]):
            uia.press(d["hwnd"], name="Don't Save")
        time.sleep(1.5)
        self.assertFalse(winapi.is_window(self.hw))

    def test_04_privacy_blocks(self):
        w = {"name": "notepad", "title": "secrets.env - Notepad", "exe": "notepad.exe"}
        with self.assertRaises(screen.Blocked):
            screen.check_allowed(w)
        with self.assertRaises(screen.Blocked):
            screen.check_allowed({"name": "KeePass", "title": "x", "exe": "keepass.exe"})
        store.set_("perm.screen", False)
        try:
            r = self.tool("ui_read", app="explorer")
            self.assertFalse(r["ok"])
        finally:
            store.set_("perm.screen", True)

    def test_05_permission_switch_and_estop(self):
        store.set_("perm.keyboard", False)
        r = self.tool("ui_type", app="notepad", text="x")
        self.assertTrue(r.get("denied"), r)
        store.set_("perm.keyboard", True)
        self.api("estop", {"on": True})
        try:
            r = self.tool("app_launch", name="notepad")
            self.assertTrue(r.get("denied") and "Emergency" in r["error"], r)
            self.assertTrue(self.api("overview")["estop"]["on"])
        finally:
            self.api("estop", {"on": False})
        self.assertFalse(self.api("overview")["estop"]["on"])

    def test_06_approval_for_high_risk_shell(self):
        victim = os.path.join(_tmp, "victim.txt")
        open(victim, "w").write("x")
        res = {}
        t = threading.Thread(target=lambda: res.update(r=self.tool("shell_run", command=f"Remove-Item '{victim}'", cwd=_tmp)), daemon=True)
        t.start()
        for _ in range(60):
            if self.api("approvals")["pending"]:
                break
            time.sleep(0.2)
        p = self.api("approvals")["pending"][0]
        self.assertEqual(p["risk"], "high")
        self.assertTrue(os.path.exists(victim), "nothing may run before approval")
        self.assertTrue(self.api("approvals/decide", {"id": p["id"], "decision": "approve"})["ok"])
        t.join(30)
        self.assertTrue(res["r"]["ok"], res)
        self.assertFalse(os.path.exists(victim))
        # rejected one does not run
        open(victim, "w").write("x")
        t = threading.Thread(target=lambda: res.update(r2=self.tool("shell_run", command=f"Remove-Item '{victim}'", cwd=_tmp)), daemon=True)
        t.start()
        for _ in range(60):
            if self.api("approvals")["pending"]:
                break
            time.sleep(0.2)
        self.api("approvals/decide", {"id": self.api("approvals")["pending"][0]["id"], "decision": "reject"})
        t.join(30)
        self.assertFalse(res["r2"]["ok"])
        self.assertTrue(os.path.exists(victim))
        self.assertTrue([a for a in self.api("audit") if a["decision"] == "rejected"])

    def test_07_low_risk_shell_and_outside_folder(self):
        r = self.tool("shell_run", command="git --version", cwd=_tmp)
        self.assertTrue(r["ok"], r)
        self.assertIn("git version", r["result"]["output"])
        r = self.tool("shell_run", command="dir", cwd="C:\\Windows")
        self.assertFalse(r["ok"])
        self.assertTrue(self.tool("file_read", path="C:\\Windows\\win.ini")["denied"])
        open(os.path.join(_tmp, ".env"), "w").write("SECRET=1")
        self.assertTrue(self.tool("file_read", path=os.path.join(_tmp, ".env"))["denied"])

    def test_08_commander_and_tasks_memory(self):
        from core import commander, memory
        r = commander.handle("add task finish the live test due 2031-01-02")
        self.assertIn("Task #", r["reply"])
        self.assertTrue([t for t in memory.list_tasks() if t["title"] == "finish the live test"])
        r = commander.handle("system status")
        self.assertIn("CPU", r["reply"])
        r = commander.handle("remember that live tests passed")
        self.assertIn("Remembered", r["reply"])
        r = commander.handle("which apps are running")
        self.assertIn("Running", r["reply"])
        r = commander.handle("what are my projects")
        self.assertIn("hukum-desktop", r["reply"].lower())
        r = commander.handle("tell me a joke")
        self.assertEqual(r["via"], "none")                      # no AI configured: says so, does not pretend

    def test_09_settings_api_changes_behaviour(self):
        r = self.api("settings", {"key": "monitor.interval_s", "value": 2})
        self.assertIn("error", r)
        self.assertEqual(self.api("settings", {"key": "monitor.interval_s", "value": 20})["value"], 20)
        self.assertEqual(monitor.status()["interval_s"], 20)
        self.assertIn("error", self.api("settings", {"key": "ui.accent", "value": "red"}))

    def test_10_projects_and_servers(self):
        ps = self.api("projects")
        self.assertTrue(any(p["name"] == "hukum-desktop" for p in ps["projects"]) or ps["projects"])
        # a real listening server is detected with its port
        import http.server
        import socketserver
        srv = socketserver.TCPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ports = [p for s in projects.dev_servers() for p in s["ports"]]
            self.assertIn(srv.server_address[1], ports)
        finally:
            srv.shutdown()

    def test_11_monitor_lifecycle_and_detection(self):
        monitor.stop()
        self.assertEqual(monitor.tick().get("skipped"), "not running")
        monitor.start(["notepad"])
        self.assertEqual(monitor.status()["mode"], "running")
        monitor.pause()
        self.assertEqual(monitor.status()["mode"], "paused")
        monitor.resume()
        permissions.estop("t")
        self.assertEqual(monitor.status()["mode"], "paused")              # e-stop pauses monitoring
        permissions.release()
        monitor.stop()
        self.assertEqual(monitor.status()["mode"], "stopped")

    def test_12_agent_job_with_dependency_and_cancel(self):
        if not agents.drivers()["antigravity"]["available"]:
            self.skipTest("agy not installed")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        a = agents.submit("antigravity", repo, "Reply with exactly the single word PONG. Do not use any tools or run commands.", readonly=True)
        b = agents.submit("antigravity", repo, "Reply with exactly the single word DONE2. Do not use any tools or run commands.", readonly=True, deps=[a["id"]])
        c = agents.submit("antigravity", repo, "Reply with OK.", readonly=True, deps=[b["id"]])
        time.sleep(1)
        self.assertEqual(agents.get(b["id"])["status"], "queued")        # waits for its dependency
        self.assertTrue(agents.cancel(c["id"]))
        for _ in range(120):
            if agents.get(b["id"])["status"] in ("done", "failed"):
                break
            time.sleep(2)
        self.assertEqual(agents.get(a["id"])["status"], "done")
        self.assertIn("PONG", agents.get(a["id"])["output"])
        self.assertEqual(agents.get(b["id"])["status"], "done")
        self.assertEqual(agents.get(c["id"])["status"], "cancelled")
        with self.assertRaises(ValueError):
            agents.submit("antigravity", "C:\\Windows", "x")             # outside allowed folders

    def test_13_phone_job_rules(self):
        # jobs from the phone: low/medium/high run (the phone approval is Boss's), critical is refused
        out = server.execute_job("run", {"command": "git --version", "cwd": _tmp}, "j1")
        self.assertIn("git version", out)
        with self.assertRaises(permissions.Denied):
            server.execute_job("run", {"command": "terraform destroy", "cwd": _tmp}, "j2")
        with self.assertRaises(ValueError):
            server.execute_job("launch_rockets", {}, "j3")

    def test_14_notifications_and_ui_files(self):
        self.api("notifications/test", {})
        n = self.api("notifications")
        self.assertTrue(n["items"])
        self.api("notifications/ack", {"all": True})
        self.assertEqual(self.api("notifications")["counts"], {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/", None, {"X-Token": self.tok})
        html = urllib.request.urlopen(req).read().decode()
        self.assertIn("HUKUM", html)
        # path traversal is refused
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/..%5Ccore%5Cstore.py", None, {"X-Token": self.tok})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(req)


if __name__ == "__main__":
    unittest.main()
