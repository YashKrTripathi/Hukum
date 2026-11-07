"""The phone app's data path, end to end: phone request -> real gateway (/api/desktop) -> PC job channel -> Hukum Desktop
(gateway link + relay allow-list + permission rules) -> JSON back. Uses exactly the paths and fields the Android app reads."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

LIVE = sys.platform == "win32" and os.environ.get("HUKUM_LIVE", "1") != "0"
HERE = os.path.dirname(os.path.abspath(__file__))
_tmp = tempfile.mkdtemp(prefix="hukum_relay_")
os.environ["HUKUM_DATA"] = _tmp
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "placement-agents"))
HAVE_GATEWAY = os.path.exists(os.path.join(os.path.dirname(os.path.dirname(HERE)), "placement-agents", "webserver.py"))


@unittest.skipUnless(LIVE and HAVE_GATEWAY, "needs Windows and the placement-agents gateway next to it")
class PhoneRelay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        config.DB_PATH = os.path.join(_tmp, "gw.db")
        import db
        db.init()
        import pcbridge, webserver
        from http.server import ThreadingHTTPServer
        cls.gw = ThreadingHTTPServer(("127.0.0.1", 0), webserver.H)
        cls.gw.daemon_threads = True
        threading.Thread(target=cls.gw.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.gw.server_address[1]}"
        cls.phone_key = webserver.key()
        from core import store, gateway, server, tools
        store.init()
        store.set_("folders.allowed", os.path.dirname(HERE) + "," + _tmp)
        store.set_("confirm.medium", "ask")                  # phone requests must NOT depend on this: the phone approval counts
        store.set_("gateway.url", cls.base)
        store.set_("gateway.pc_key", pcbridge.pc_key())
        store.set_("gateway.link", True)
        gateway.start(server.execute_job)
        for _ in range(60):
            if pcbridge.online():
                break
            time.sleep(0.5)
        cls.server, cls.store, cls.tools = server, store, tools

    @classmethod
    def tearDownClass(cls):
        cls.store.set_("gateway.link", False)
        cls.gw.shutdown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + "/api/desktop", json.dumps({"method": method, "path": path, "body": body or {}}).encode(),
                                     {"X-Key": self.phone_key, "Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=45).read())
        return r["status"], r["data"]

    def test_01_home_shape_the_app_reads(self):
        st, d = self.call("GET", "/api/m/home")
        self.assertEqual(st, 200)
        for k in ("cpu", "ram", "monitor", "context", "observations", "notif", "agents", "tasks", "approvals", "estop", "ai", "pc", "battery"):
            self.assertIn(k, d, k)
        self.assertIn("counts", d["notif"])
        self.assertIn("on", d["estop"])

    def test_02_every_screen_endpoint(self):
        for path, keys in (("/api/agents", ("drivers", "jobs")), ("/api/projects", ("projects", "servers")), ("/api/notifications", ("items", "counts")),
                           ("/api/system", ("now", "summary", "findings", "top_cpu", "top_mem")), ("/api/monitor", ("status", "recent")),
                           ("/api/approvals", ("pending",)), ("/api/workflows", ("items",)), ("/api/whatsapp", ("history",))):
            st, d = self.call("GET", path)
            self.assertEqual(st, 200, path)
            for k in keys:
                self.assertIn(k, d, f"{path} missing {k}")
        for path in ("/api/apps", "/api/tasks", "/api/memory", "/api/audit"):
            st, d = self.call("GET", path)
            self.assertEqual(st, 200, path)
            self.assertIsInstance(d, list, path)

    def test_03_tasks_memory_roundtrip(self):
        st, t = self.call("POST", "/api/tasks", {"title": "from the phone", "due": ""})
        self.assertEqual(st, 200)
        self.call("POST", "/api/tasks/update", {"id": t["id"], "status": "doing"})
        self.assertEqual([x for x in self.call("GET", "/api/tasks")[1] if x["id"] == t["id"]][0]["status"], "doing")
        self.call("POST", "/api/tasks/delete", {"id": t["id"]})
        self.assertFalse([x for x in self.call("GET", "/api/tasks")[1] if x["id"] == t["id"]])
        st, m = self.call("POST", "/api/memory", {"text": "phone memory test"})
        self.assertEqual(st, 200)
        self.call("POST", "/api/memory/forget", {"id": m["id"]})

    def test_04_chat_via_phone(self):
        st, r = self.call("POST", "/api/m/chat", {"text": "add task relay chat task"})
        for _ in range(30):
            st, res = self.call("GET", "/api/m/chat_result?id=" + r["id"])
            if res.get("done"):
                break
            time.sleep(0.5)
        self.assertTrue(res["done"])
        self.assertIn("Task #", res["reply"])

    def test_05_phone_approval_counts_but_critical_is_refused(self):
        # medium-risk action runs although the PC is set to 'ask': the phone's own confirmation is the approval
        st, d = self.call("POST", "/api/tools/call", {"name": "file_write", "args": {"path": os.path.join(_tmp, "p.txt"), "text": "hi"}})
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"], d)
        self.assertTrue(os.path.exists(os.path.join(_tmp, "p.txt")))
        st, d = self.call("POST", "/api/tools/call", {"name": "shell_run", "args": {"command": "terraform destroy", "cwd": _tmp}})
        self.assertFalse(d["ok"])
        self.assertIn("cannot be started from the phone", d["error"])
        # estop from the phone blocks everything, even phone-approved actions
        self.call("POST", "/api/estop", {"on": True})
        try:
            st, d = self.call("POST", "/api/tools/call", {"name": "file_write", "args": {"path": os.path.join(_tmp, "q.txt"), "text": "hi"}})
            self.assertFalse(d["ok"])
            self.assertFalse(os.path.exists(os.path.join(_tmp, "q.txt")))
            self.assertTrue(self.call("GET", "/api/m/home")[1]["estop"]["on"])
        finally:
            self.call("POST", "/api/estop", {"on": False})
        self.assertFalse(self.call("GET", "/api/m/home")[1]["estop"]["on"])

    def test_06_allow_list(self):
        st, d = self.call("POST", "/api/settings", {"key": "perm.files", "value": False})
        self.assertEqual(st, 403)
        st, d = self.call("POST", "/api/quit", {})
        self.assertEqual(st, 403)
        self.assertTrue(self.store.get("perm.files"))
        st, d = self.call("GET", "/api/settings")
        self.assertEqual(st, 403)                              # settings (and secrets) never leave the PC

    def test_07_critical_approval_not_from_phone(self):
        import threading as th
        res = {}
        def attempt():
            try:
                res["r"] = self.server.permissions.run("t", "deploy.prod", {}, lambda: "x")
            except Exception as e:
                res["r"] = e
        t = th.Thread(target=attempt, daemon=True)
        t.start()
        for _ in range(40):
            if self.server.permissions.pending():
                break
            time.sleep(0.1)
        pid = self.server.permissions.pending()[0]["id"]
        st, d = self.call("POST", "/api/approvals/decide", {"id": pid, "decision": "approve", "typed": "CONFIRM"})
        self.assertFalse(d["ok"])
        self.assertIn("at the PC", d["error"])
        self.call("POST", "/api/approvals/decide", {"id": pid, "decision": "reject"})      # rejecting is always allowed
        t.join(10)

    def test_08_offline_and_auth(self):
        req = urllib.request.Request(self.base + "/api/desktop", b"{}", {"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(req)
        self.assertEqual(c.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
