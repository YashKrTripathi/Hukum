"""Hukum PC agent: the PC body of Hukum. Runs on Boss's PC, connects OUT to the gateway (no open ports) and
executes jobs Hukum sends: open things, read files, run shell commands, run coding agents in your repos.

    python hukum_pc.py            (first run writes hukum_pc.json next to this file; edit it, run again)

Safety: everything is limited to the folders in "roots"; shell commands matching "deny" are refused; the gateway
only sends shell/coding jobs after you said yes to Hukum. Stop the agent (Ctrl+C or the stop file) = PC is offline
to Hukum. Standard library only.
Config keys: gateway, pc_key, roots, repos{alias: folder}, apps{name: command}, agents{name: [argv...]}, claude_tools,
run_timeout, deny[]"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.environ.get("HUKUM_PC_CONFIG", os.path.join(HERE, "hukum_pc.json"))
STOP_FILE = os.path.join(HERE, "STOP_HUKUM_PC")

DEFAULT_CFG = {
    "gateway": "http://crm.dypiu.ac.in:8765",
    "pc_key": "PASTE_THE_PC_KEY_HERE",
    "roots": ["D:\\learn"],
    "repos": {"hukum-android": "D:\\learn\\hukum-android", "hukum-gateway": "D:\\learn\\placement-agents",
              "unisyncai": "D:\\learn\\college-ai-platform"},
    "apps": {"chrome": "chrome.exe", "vscode": "code", "notepad": "notepad.exe", "explorer": "explorer.exe"},
    "agents": {
        "claude": ["claude", "-p", "--permission-mode", "acceptEdits", "--allowedTools", "{claude_tools}"],
        "hermes": ["hermes", "chat", "-Q", "--oneshot", "--reasoning", "none", "-q", "{prompt}"],
    },
    "claude_tools": "Read,Glob,Grep,Edit,Write,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(python -m unittest:*)",
    "run_timeout": 120,
    "deny": [r"\bformat\s+[a-z]:", r"\brm\s+-rf\s+/", r"\bdel\s+/[sfq]", r"\brd\s+/s", r"\brmdir\s+/s",
             r"\bshutdown\b", r"\breg\s+(add|delete)", r"\bdiskpart\b", r"\bcipher\s+/w", r"\bnet\s+user\b",
             r"\bschtasks\b", r"Remove-Item\s+.*-Recurse", r"\bgit\s+push\s+.*--force", r"\bgit\s+reset\s+--hard"],
}


def load_cfg():
    if not os.path.exists(CFG_PATH):
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CFG, f, indent=2)
        print(f"Wrote {CFG_PATH}. Put the PC key in it (on the gateway server: python -c \"import db,pcbridge;db.init();"
              f"print(pcbridge.pc_key())\"), check the folders, then run again.")
        sys.exit(0)
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CFG.items():
        cfg.setdefault(k, v)
    return cfg


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.roots = [os.path.realpath(r) for r in cfg["roots"]]
        self.deny = [re.compile(p, re.I) for p in cfg["deny"]]
        self.procs = {}          # job id -> Popen (coding tasks and commands)
        self.lock = threading.Lock()

    # ---------- http ----------
    def _req(self, method, path, body=None, timeout=40):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.cfg["gateway"].rstrip("/") + path, data=data, method=method,
                                   headers={"X-PC-Key": self.cfg["pc_key"], "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")

    def report(self, jid, status, output):
        for _ in range(3):
            try:
                self._req("POST", "/api/pc/result", {"id": jid, "status": status, "output": output}, timeout=20)
                return
            except Exception:
                time.sleep(2)

    # ---------- path safety ----------
    def inside(self, p):
        rp = os.path.realpath(p)
        return any(os.path.commonpath([rp, r]) == r for r in self.roots if os.path.splitdrive(rp)[0] == os.path.splitdrive(r)[0])

    def resolve_dir(self, repo_or_path):
        v = (repo_or_path or "").strip()
        p = self.cfg["repos"].get(v) or self.cfg["repos"].get(v.lower()) or v or self.roots[0]
        p = os.path.realpath(p)
        if not os.path.isdir(p) or not self.inside(p):
            raise ValueError(f"folder not allowed or missing: {repo_or_path}")
        return p

    # ---------- jobs ----------
    def handle(self, job):
        jid, kind, a = job["id"], job["kind"], job.get("args") or {}
        try:
            if kind == "open":
                out = self.do_open(a["target"])
            elif kind == "read":
                out = self.do_read(a["path"])
            elif kind == "run":
                out = self.do_run(jid, a["command"], a.get("cwd"))
            elif kind == "code":
                return self.do_code(jid, a)
            elif kind == "stop":
                out = self.do_stop(a.get("job", ""))
            else:
                out = f"unknown job kind {kind}"
                return self.report(jid, "failed", out)
            self.report(jid, "done", out)
        except Exception as e:
            self.report(jid, "failed", f"{type(e).__name__}: {e}")

    def do_open(self, target):
        t = target.strip()
        if re.match(r"https?://", t, re.I):
            os.startfile(t) if hasattr(os, "startfile") else subprocess.Popen(["xdg-open", t])
            return f"opened {t}"
        app = self.cfg["apps"].get(t.lower())
        if app:
            subprocess.Popen(app, shell=True)
            return f"started {t}"
        if os.path.exists(t) and self.inside(t):
            os.startfile(t) if hasattr(os, "startfile") else subprocess.Popen(["xdg-open", t])
            return f"opened {t}"
        raise ValueError(f"not an allowed app/URL/path: {t} (apps: {', '.join(self.cfg['apps'])})")

    def do_read(self, path):
        p = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.roots[0], path))
        if not self.inside(p):
            raise ValueError("outside the allowed folders")
        if os.path.isdir(p):
            names = sorted(os.listdir(p))[:80]
            return "\n".join(n + ("/" if os.path.isdir(os.path.join(p, n)) else "") for n in names) or "(empty)"
        if os.path.getsize(p) > 200_000:
            raise ValueError("file too large (200 KB limit)")
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(6000)

    def do_run(self, jid, command, cwd):
        for rx in self.deny:
            if rx.search(command):
                raise ValueError(f"blocked by the deny list: {rx.pattern}")
        d = self.resolve_dir(cwd)
        p = subprocess.Popen(command, shell=True, cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, text=True, errors="replace")
        with self.lock:
            self.procs[jid] = p
        try:
            out, _ = p.communicate(timeout=int(self.cfg["run_timeout"]))
        except subprocess.TimeoutExpired:
            self.kill(p)
            out = "(timed out and was stopped)"
        finally:
            with self.lock:
                self.procs.pop(jid, None)
        return f"exit {p.returncode}\n{(out or '')[-3500:]}"

    def kill(self, p):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            else:
                p.kill()
        except Exception:
            pass

    def do_stop(self, jid):
        with self.lock:
            p = self.procs.get(jid)
        if not p:
            return f"{jid} is not running here"
        self.kill(p)
        self.report(jid, "stopped", "stopped on request")
        return f"stopped {jid}"

    def do_code(self, jid, a):
        d = self.resolve_dir(a.get("repo"))
        name = a.get("agent") or "claude"
        argv = self.cfg["agents"].get(name)
        if not argv:
            raise ValueError(f"unknown agent {name}")
        prompt = str(a.get("prompt", ""))
        use_stdin = not any("{prompt}" in x for x in argv)
        argv = [x.replace("{prompt}", prompt).replace("{claude_tools}", self.cfg["claude_tools"]) for x in argv]
        exe = shutil.which(argv[0])
        if not exe:
            raise ValueError(f"{argv[0]} not found on this PC's PATH")
        argv[0] = exe
        p = subprocess.Popen(argv, cwd=d, stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        with self.lock:
            self.procs[jid] = p
        if use_stdin:
            try:
                p.stdin.write(prompt)
                p.stdin.close()
            except OSError:
                pass
        buf = []

        def reader():
            for line in p.stdout:
                buf.append(line)
                del buf[:-200]
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        self.report(jid, "running", f"started {name} in {d}")
        last = ""
        while p.poll() is None:
            time.sleep(10)
            cur = "".join(buf)[-2500:]
            if cur != last and p.poll() is None:
                self.report(jid, "running", cur)
                last = cur
        t.join(timeout=5)
        with self.lock:
            self.procs.pop(jid, None)
        out = "".join(buf)[-3000:]
        self.report(jid, "done" if p.returncode == 0 else "failed", f"exit {p.returncode}\n{out}")

    # ---------- main loop ----------
    def loop(self):
        print(f"Hukum PC agent online -> {self.cfg['gateway']}  (roots: {', '.join(self.roots)})")
        backoff = 3
        while not os.path.exists(STOP_FILE):
            try:
                jobs = self._req("GET", "/api/pc/poll?wait=25", timeout=40).get("jobs", [])
                backoff = 3
                for j in jobs:
                    print(time.strftime("%H:%M:%S"), j["id"], j["kind"], str(j.get("args"))[:100])
                    threading.Thread(target=self.handle, args=(j,), daemon=True).start()
            except urllib.error.HTTPError as e:
                print("gateway said", e.code, "(wrong PC key?)")
                time.sleep(30)
            except Exception as e:
                print("gateway unreachable:", type(e).__name__, "retry in", backoff, "s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        print("stop file found, exiting")


if __name__ == "__main__":
    Agent(load_cfg()).loop()
