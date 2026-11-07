"""Portable tests: settings, permission rules, redaction, detectors, parser, tasks/memory, workflows. No desktop needed."""
import os
import sys
import tempfile
import time
import unittest

_tmp = tempfile.mkdtemp(prefix="hukum_test_")
os.environ["HUKUM_DATA"] = _tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, permissions, redact, monitor, commander, memory, automation, notify, ai, events  # noqa: E402

store.init()


class Settings(unittest.TestCase):
    def test_types_and_ranges(self):
        self.assertEqual(store.coerce("monitor.interval_s", "15"), 15)
        with self.assertRaises(ValueError):
            store.coerce("monitor.interval_s", "1")
        with self.assertRaises(ValueError):
            store.coerce("ui.accent", "blue")
        with self.assertRaises(ValueError):
            store.coerce("gateway.url", "ftp://x")
        with self.assertRaises(ValueError):
            store.coerce("nope", 1)

    def test_roundtrip_and_listener(self):
        seen = []
        store.on_change(lambda k, v: seen.append((k, v)))
        store.set_("ui.font_size", 16)
        self.assertEqual(store.get("ui.font_size"), 16)
        self.assertIn(("ui.font_size", 16), seen)
        store.set_("ui.font_size", 14)

    def test_secrets_never_described(self):
        d = {i["key"]: i for i in store.describe()}
        self.assertEqual(d["ai.api_key"]["value"], "")
        self.assertIn("is_set", d["ai.api_key"])


class Redaction(unittest.TestCase):
    def test_secrets_removed(self):
        for s in ("my key sk-abcdefghijklmnopqrstuvwx1234", "password: hunter2hunter2", "card 4111 1111 1111 1111", "Bearer abcdefghijklmnopqrstuvwxyz123456"):
            out = redact.redact(s)
            self.assertNotIn("hunter2", out)
            self.assertNotIn("4111 1111", out)
            self.assertNotIn("sk-abcdefghijkl", out)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", out)


class Risk(unittest.TestCase):
    def test_shell_classification(self):
        c = permissions.classify_shell
        self.assertEqual(c("git status"), "low")
        self.assertEqual(c("dir"), "low")
        self.assertEqual(c("npm install"), "medium")
        self.assertEqual(c("git push --force origin main"), "high")
        self.assertEqual(c("Remove-Item foo.txt"), "high")
        self.assertEqual(c("terraform destroy"), "critical")
        self.assertEqual(c("rm -rf /"), "critical")
        self.assertEqual(c("git status && rm foo"), "high")          # a chain is as risky as its worst part
        self.assertEqual(c("ssh root@server"), "high")

    def test_decisions(self):
        store.set_("confirm.medium", "ask")
        self.assertEqual(permissions.decision("ui.type", {})[0], "ask")
        self.assertEqual(permissions.decision("ui.type", {}, preapproved=True)[0], "allow")
        self.assertEqual(permissions.decision("app.list", {})[0], "allow")
        self.assertEqual(permissions.decision("deploy.prod", {}, preapproved=True)[0], "ask")      # critical never pre-approved
        store.set_("perm.keyboard", False)
        self.assertEqual(permissions.decision("ui.type", {}, preapproved=True)[0], "deny")
        store.set_("perm.keyboard", True)
        store.set_("confirm.medium", "ask")

    def test_estop_blocks(self):
        permissions.estop("test")
        try:
            self.assertEqual(permissions.decision("ui.type", {}, True)[0], "deny")
            self.assertEqual(permissions.decision("app.launch", {})[0], "deny")
            with self.assertRaises(permissions.Denied):
                permissions.run("t", "app.launch", {}, lambda: 1)
        finally:
            permissions.release()
        self.assertEqual(permissions.decision("app.launch", {})[0], "allow")

    def test_approval_flow_and_confirm_word(self):
        import threading
        out = {}
        threading.Thread(target=lambda: out.update(r=self._try(permissions.run, "t", "deploy.prod", {}, lambda: "deployed")), daemon=True).start()
        for _ in range(50):
            if permissions.pending():
                break
            time.sleep(0.1)
        p = permissions.pending()[0]
        with self.assertRaises(permissions.Denied):
            permissions.approve(p["id"], "yes")
        self.assertTrue(permissions.approve(p["id"], "CONFIRM"))
        for _ in range(50):
            if "r" in out:
                break
            time.sleep(0.1)
        self.assertEqual(out["r"], "deployed")
        # rejection
        threading.Thread(target=lambda: out.update(r2=self._try(permissions.run, "t", "msg.send", {"contact": "x"}, lambda: "sent")), daemon=True).start()
        for _ in range(50):
            if permissions.pending():
                break
            time.sleep(0.1)
        permissions.reject(permissions.pending()[0]["id"])
        for _ in range(50):
            if "r2" in out:
                break
            time.sleep(0.1)
        self.assertIsInstance(out["r2"], permissions.Denied)
        self.assertTrue(store.q("SELECT * FROM audit WHERE action='msg.send' AND decision='rejected'"))

    @staticmethod
    def _try(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            return e


class Detectors(unittest.TestCase):
    def ids(self, text, kind="terminal"):
        return {d["id"] for d in monitor.detect(text, kind)}

    def test_found(self):
        self.assertIn("npm_fail", self.ids("npm ERR! code ELIFECYCLE"))
        self.assertIn("port_busy", self.ids("Error: listen EADDRINUSE: address already in use :::3000"))
        self.assertIn("port_busy", self.ids("Port 3000 is already in use"))
        self.assertIn("py_traceback", self.ids("Traceback (most recent call last):\n  File"))
        self.assertIn("needs_input", self.ids("Proceed? (y/n)"))
        self.assertIn("agent_permission", self.ids("Do you want to proceed with this edit?", "coding-agent"))
        self.assertIn("agent_done", self.ids("Task completed successfully", "coding-agent"))
        self.assertIn("browser_error", self.ids("ERR_CONNECTION_REFUSED", "browser"))
        self.assertIn("server_up", self.ids("VITE ready in 312 ms\n  Local:   http://localhost:5173/"))

    def test_kind_scoping_and_quiet(self):
        self.assertNotIn("needs_input", self.ids("Proceed? (y/n)", "browser"))
        self.assertEqual(self.ids("hello world, all good here"), set())

    def test_secret_not_in_finding(self):
        f = monitor.detect("npm ERR! token=sk-abcdefghijklmnopqrstuvwx1234", "terminal")
        self.assertNotIn("sk-abcdefghijkl", f[0]["line"])


class Parser(unittest.TestCase):
    def plan(self, t):
        return commander.plan_rules(t)

    def test_commands(self):
        self.assertEqual(self.plan("open vscode")[0]["tool"], "app_launch")
        self.assertEqual(self.plan("open vscode in D:\\learn")[0]["args"]["path"], "D:\\learn")
        self.assertEqual(self.plan("close notepad")[0]["tool"], "app_close")
        self.assertEqual(self.plan("why is my laptop slow")[0]["tool"], "system_status")
        self.assertEqual(self.plan("what are my projects")[0]["tool"], "project_list")
        self.assertEqual(self.plan("type \"hello\" in notepad")[0]["args"], {"app": "notepad", "text": "hello"})
        self.assertEqual(self.plan("add task fix login due 2026-12-01")[0]["args"]["due"], "2026-12-01")
        s = self.plan("message Rahul: I will be late")[0]
        self.assertEqual((s["tool"], s["args"]["contact"], s["args"]["text"]), ("msg_send", "Rahul", "I will be late"))
        a = self.plan("ask codex to fix the failing tests in placement-agents")[0]["args"]
        self.assertEqual((a["agent"], a["project"], a["readonly"]), ("codex", "placement-agents", False))
        self.assertTrue(self.plan("ask antigravity to review the code in college-ai-platform")[0]["args"]["readonly"])
        self.assertEqual(self.plan("emergency stop")[0]["tool"], "__estop")
        self.assertIsNone(self.plan("tell me a joke about cats"))


class MemoryTasks(unittest.TestCase):
    def test_memory(self):
        m = memory.remember("Boss prefers dark dashboards", "pref")
        self.assertTrue(memory.recall("dark dashboards"))
        memory.forget(m["id"])
        self.assertFalse(memory.recall("dark dashboards"))
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx1234", memory.remember("key sk-abcdefghijklmnopqrstuvwx1234")["text"])

    def test_tasks_deps_and_overdue(self):
        a = memory.add_task("write spec", due="2020-01-01")
        b = memory.add_task("build it", deps=[a["id"]])
        self.assertTrue(next(t for t in memory.list_tasks() if t["id"] == a["id"])["overdue"])
        self.assertTrue(next(t for t in memory.list_tasks() if t["id"] == b["id"])["blocked"])
        memory.update_task(a["id"], status="done")
        self.assertFalse(next(t for t in memory.list_tasks() if t["id"] == b["id"])["blocked"])
        with self.assertRaises(ValueError):
            memory.update_task(a["id"], status="bogus")
        with self.assertRaises(ValueError):
            memory.add_task("x", due="tomorrow")


class Notifications(unittest.TestCase):
    def test_grouping_and_severity(self):
        store.set_("notify.toast", False)
        a = notify.notify("error", "Build failed", "x", key="k1", force=True)
        b = notify.notify("error", "Build failed", "y", key="k1")
        self.assertTrue(b.get("grouped"))
        self.assertEqual(store.one("SELECT count FROM notifications WHERE id=?", (a["id"],))["count"], 2)
        low = notify.notify("info", "FYI", "", key="k2")
        self.assertFalse(low["raised"])             # below monitor.alert_min_severity
        notify.ack_all()
        self.assertEqual(notify.counts(), {})


class Workflows(unittest.TestCase):
    def test_validation(self):
        for bad in ({}, {"trigger": {"type": "schedule"}, "steps": [{"tool": "notify"}]}, {"trigger": {"type": "manual"}, "steps": []},
                    {"trigger": {"type": "manual"}, "steps": [{"tool": "launch_missiles"}]}, {"trigger": {"type": "interval", "minutes": 0}, "steps": [{"tool": "notify"}]}):
            with self.assertRaises(ValueError):
                automation.validate(bad)

    def test_run_logs_and_conditions(self):
        wf = automation.save("t1", {"trigger": {"type": "manual"}, "steps": [{"tool": "task_add", "args": {"title": "from workflow"}}]})
        r = automation.run(wf)
        self.assertEqual(r["status"], "ok")
        self.assertTrue([t for t in memory.list_tasks() if t["title"] == "from workflow"])
        wf2 = automation.save("t2", {"trigger": {"type": "schedule", "at": "00:00"}, "conditions": [{"type": "time_between", "from": "00:00", "to": "00:00"}],
                                     "steps": [{"tool": "task_add", "args": {"title": "never"}}]})
        wf2["spec"]["conditions"] = [{"type": "weekday", "days": ["xyz"]}]
        self.assertEqual(automation.run(wf2, "schedule")["status"], "skipped")
        bad = automation.save("t3", {"trigger": {"type": "manual"}, "steps": [{"tool": "task_add", "args": {"nope": 1}}]})
        self.assertEqual(automation.run(bad)["status"], "failed")

    def test_event_trigger(self):
        automation.save("onfail", {"trigger": {"type": "event", "match": "disk full"}, "steps": [{"tool": "task_add", "args": {"title": "free disk"}}]})
        automation.start()
        notify.notify("error", "Disk full on D:", "", key="df", force=True)
        for _ in range(40):
            if [t for t in memory.list_tasks() if t["title"] == "free disk"]:
                break
            time.sleep(0.1)
        self.assertTrue([t for t in memory.list_tasks() if t["title"] == "free disk"])
        automation.stop()


class AIRouter(unittest.TestCase):
    def test_local_only_blocks_cloud(self):
        store.set_("ai.base_url", "https://api.example.com/v1")
        store.set_("ai.model", "m")
        store.set_("ai.local_only", True)
        try:
            self.assertFalse(ai.available())
            with self.assertRaises(RuntimeError) as c:
                ai.chat([{"role": "user", "content": "hi"}])
            self.assertIn("local-only", str(c.exception))
        finally:
            store.set_("ai.local_only", False)

    def test_fake_endpoint(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen["body"], seen["auth"] = body, self.headers.get("Authorization")
                reply = json.dumps({"model": "fake", "choices": [{"message": {"content": '{"reply":"ok","steps":[{"tool":"system_status","args":{}}]}'}}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(reply))); self.end_headers(); self.wfile.write(reply)
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        store.set_("ai.base_url", f"http://127.0.0.1:{srv.server_port}/v1")
        store.set_("ai.model", "fake")
        self.assertTrue(ai.available())
        r = ai.chat([{"role": "user", "content": "my key is sk-abcdefghijklmnopqrstuvwx1234"}])
        self.assertEqual(r["model"], "fake")
        self.assertNotIn("sk-abcdefghijkl", json.dumps(seen["body"]))       # redacted before leaving
        reply, steps = commander.plan_llm("how is the pc")
        self.assertEqual(steps[0]["tool"], "system_status")
        srv.shutdown()


class Events(unittest.TestCase):
    def test_bus(self):
        i = events.latest_id()
        events.emit("x", {"a": 1})
        got = events.since(i, wait=1)
        self.assertEqual(got[-1]["type"], "x")


if __name__ == "__main__":
    unittest.main()
