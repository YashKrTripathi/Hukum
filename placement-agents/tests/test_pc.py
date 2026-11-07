"""End-to-end test of the PC body: gateway (real webserver) + hukum_pc agent + Hukum's tools. No LLM needed."""
import json, os, sys, tempfile, threading, time, unittest
from http.server import ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config
TMP = tempfile.mkdtemp()
config.DB_PATH = os.path.join(TMP, "test.db")
import db; db.init()
import pcbridge, webserver, chat_agent, hukum_pc


class PCTests(unittest.TestCase):
    def test_flow(self):
        chat_agent._tl.actions = []
        tool = chat_agent.run_tool
        # offline before the agent connects
        self.assertIn("offline", tool("pc_run", {"command": "echo x", "confirmed": True}).lower())
        self.assertIn("OFFLINE", tool("pc_status", {}))

        srv = ThreadingHTTPServer(("127.0.0.1", 0), webserver.H); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        work = os.path.join(TMP, "repo"); os.makedirs(work)
        open(os.path.join(work, "note.txt"), "w").write("hello from file")
        cfg = dict(hukum_pc.DEFAULT_CFG, gateway=f"http://127.0.0.1:{srv.server_address[1]}", pc_key=pcbridge.pc_key(),
                   roots=[TMP], repos={"t": work},
                   agents={"echo": [sys.executable, "-c", "import sys;print('agent got:'+sys.stdin.read())"]})
        agent = hukum_pc.Agent(cfg)
        threading.Thread(target=agent.loop, daemon=True).start()
        for _ in range(50):
            if pcbridge.online(): break
            time.sleep(0.1)
        self.assertTrue(pcbridge.online())
        self.assertIn("ONLINE", tool("pc_status", {}))

        # confirmation gate
        self.assertIn("NOT RUN", tool("pc_run", {"command": "echo hi", "confirmed": False}))
        out = tool("pc_run", {"command": "echo hi there", "cwd": "t", "confirmed": True})
        self.assertIn("exit 0", out); self.assertIn("hi there", out)
        # safety: deny list and folders outside the roots
        self.assertIn("blocked", tool("pc_run", {"command": "shutdown /s", "confirmed": True}))
        self.assertIn("not allowed", tool("pc_run", {"command": "echo x", "cwd": os.path.abspath(os.sep), "confirmed": True}))
        # read
        self.assertIn("note.txt", tool("pc_read", {"path": work}))
        self.assertIn("hello from file", tool("pc_read", {"path": os.path.join(work, "note.txt")}))
        self.assertIn("outside", tool("pc_read", {"path": os.path.abspath(os.sep)}))
        # coding task: gate, run, notification
        self.assertIn("NOT STARTED", tool("code_task", {"repo": "t", "prompt": "p", "agent": "echo", "confirmed": False}))
        r = tool("code_task", {"repo": "t", "prompt": "build it", "agent": "echo", "confirmed": True})
        jid = r.split()[2]
        for _ in range(60):
            if pcbridge._jobs[jid]["status"] in ("done", "failed"): break
            time.sleep(0.2)
        self.assertEqual(pcbridge._jobs[jid]["status"], "done", pcbridge._jobs[jid])
        self.assertIn("agent got:build it", tool("code_status", {"job": jid}))
        self.assertTrue(any(e["type"] == "nudge" and jid in e["text"] for e in webserver._events))
        # wrong PC key is refused
        import urllib.request, urllib.error
        req = urllib.request.Request(cfg["gateway"] + "/api/pc/poll?wait=1", headers={"X-PC-Key": "nope"})
        with self.assertRaises(urllib.error.HTTPError) as cm: urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 401)
        req = urllib.request.Request(cfg["gateway"] + "/api/pc/poll?wait=1", headers={"X-Key": webserver.key()})
        with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(req)     # phone key cannot poll jobs


if __name__ == "__main__":
    unittest.main()
