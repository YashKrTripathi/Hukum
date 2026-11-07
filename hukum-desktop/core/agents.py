"""Coding-agent orchestration. Jobs live in the database (agent_jobs). A scheduler starts queued jobs when their
dependencies are done, a slot is free (agents.max_parallel) and, for jobs that write, nobody else is writing in the
same repository. Drivers: Codex CLI (`codex exec`), Antigravity CLI (`agy -p`), and the Claude desktop app (driven
through its window: focus, paste, Enter, then watching its text). Every job records output, changed files (git) and an
optional verification command. Nothing here bypasses permissions: callers go through permissions.run('agent.run')."""
import json
import os
import shutil
import subprocess
import threading
import time

from . import store, events, notify, winapi
from .redact import redact

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_procs = {}            # job id -> Popen
_cancel = set()
_lock = threading.RLock()
_wake = threading.Event()
_started = False


def _find(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def drivers():
    """Which agents can actually run here (and how)."""
    codex = _find("codex.cmd", "codex")
    agy = _find("agy.exe", "agy")
    claude_win = None
    try:
        from . import apps
        claude_win = bool(apps.windows_of("claude"))
    except Exception:
        pass
    return {
        "codex": {"available": bool(codex), "mode": "CLI (codex exec)", "path": codex, "note": "" if codex else "codex is not on PATH"},
        "antigravity": {"available": bool(agy), "mode": "CLI (agy -p)", "path": agy, "note": "" if agy else "agy is not on PATH"},
        "claude": {"available": True, "mode": "Claude desktop app (window automation)", "path": None,
                   "note": "Open the Claude app first" if not claude_win else "Claude window found"},
    }


def _git(repo, *a):
    try:
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        return r.stdout
    except Exception:
        return ""


def _dirty(repo):
    return {ln[3:].strip() for ln in _git(repo, "status", "--porcelain").splitlines()}


# ---------------------------------------------------------------- jobs API
def submit(agent, repo, prompt, readonly=False, deps=None, verify="", task_id=None, group=""):
    agent = agent.lower().replace("agy", "antigravity")
    if agent not in ("codex", "antigravity", "claude"):
        raise ValueError("agent must be codex, antigravity or claude")
    repo = os.path.abspath(repo)
    if not os.path.isdir(repo):
        raise ValueError(f"folder not found: {repo}")
    if not any(os.path.abspath(repo).lower().startswith(os.path.abspath(r).lower()) for r in store.get_list("folders.allowed")):
        raise ValueError(f"{repo} is outside the allowed folders (Settings > Permissions)")
    d = drivers()[agent]
    if not d["available"]:
        raise ValueError(f"{agent} is not available: {d['note']}")
    now = time.time()
    jid = store.x("INSERT INTO agent_jobs(agent,repo,prompt,status,deps,readonly,verify,task_id,created,updated,group_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (agent, repo, redact(prompt)[:8000], "queued", json.dumps(deps or []), int(bool(readonly)), verify, task_id, now, now, group))
    events.emit("agent_job", {"id": jid, "status": "queued"})
    start()
    _wake.set()
    return get(jid)


def get(jid):
    r = store.one("SELECT * FROM agent_jobs WHERE id=?", (int(jid),))
    if r:
        r["deps"] = json.loads(r["deps"] or "[]")
        r["files"] = json.loads(r["files"] or "[]")
    return r


def jobs(limit=50):
    rows = store.q("SELECT * FROM agent_jobs ORDER BY id DESC LIMIT ?", (int(limit),))
    for r in rows:
        r["deps"] = json.loads(r["deps"] or "[]")
        r["files"] = json.loads(r["files"] or "[]")
        r["output"] = r["output"][-1500:]
    return rows


def _set(jid, **f):
    sets = ",".join(f"{k}=?" for k in f)
    store.x(f"UPDATE agent_jobs SET {sets}, updated=? WHERE id=?", (*[json.dumps(v) if isinstance(v, (list, dict)) else v for v in f.values()], time.time(), jid))
    events.emit("agent_job", {"id": jid, **{k: v for k, v in f.items() if k in ("status",)}})


def cancel(jid):
    jid = int(jid)
    j = get(jid)
    if not j or j["status"] in ("done", "failed", "cancelled"):
        return False
    _cancel.add(jid)
    p = _procs.get(jid)
    if p and p.poll() is None:
        winapi.kill_pid(p.pid)
    if j["status"] == "queued":
        _set(jid, status="cancelled")
    return True


def cancel_all():
    n = 0
    for j in store.q("SELECT id FROM agent_jobs WHERE status IN ('queued','running')"):
        n += cancel(j["id"])
    return n


# ---------------------------------------------------------------- scheduler
def _ready(j, running):
    for d in j["deps"]:
        dj = get(d)
        if not dj or dj["status"] in ("failed", "cancelled"):
            return "blocked"
        if dj["status"] != "done":
            return "wait"
    if len(running) >= int(store.get("agents.max_parallel")):
        return "wait"
    if not j["readonly"] and any((not r["readonly"]) and r["repo"].lower() == j["repo"].lower() for r in running):
        return "wait"                                   # one writer per repository
    return "go"


def _loop():
    while True:
        try:
            running = store.q("SELECT * FROM agent_jobs WHERE status='running'")
            for r in running:
                r["readonly"] = bool(r["readonly"])
            queued = store.q("SELECT * FROM agent_jobs WHERE status='queued' ORDER BY id")
            for j in queued:
                j["deps"] = json.loads(j["deps"] or "[]")
                j["readonly"] = bool(j["readonly"])
                st = _ready(j, running)
                if st == "blocked":
                    _set(j["id"], status="failed", output="A job this one depends on failed or was cancelled.")
                elif st == "go":
                    _set(j["id"], status="running")
                    running.append(j)
                    threading.Thread(target=_run, args=(j["id"],), daemon=True, name=f"agent-{j['id']}").start()
        except Exception:
            pass
        _wake.wait(2)
        _wake.clear()


def start():
    global _started
    if not _started:
        _started = True
        # jobs left 'running' by a previous process cannot be running now
        store.x("UPDATE agent_jobs SET status='failed', output=output||char(10)||'(Hukum restarted while this was running)' WHERE status='running'")
        threading.Thread(target=_loop, daemon=True, name="agents").start()


# ---------------------------------------------------------------- drivers
def _cmd(j):
    prompt = j["prompt"]
    if j["agent"] == "codex":
        sandbox = "read-only" if j["readonly"] else "workspace-write"
        model = store.get("agents.codex_model").strip()
        return [drivers()["codex"]["path"], "exec", "--skip-git-repo-check", "-s", sandbox, "-C", j["repo"], *(["-m", model] if model else []), prompt]
    if j["agent"] == "antigravity":
        mode = "plan" if j["readonly"] else "accept-edits"
        return [drivers()["antigravity"]["path"], "--mode", mode, "-p", prompt]
    return None


def _run_cli(j):
    cmd = _cmd(j)
    p = subprocess.Popen(cmd, cwd=j["repo"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
    _procs[j["id"]] = p
    buf = []
    last_save = [0.0]

    def pump():
        for line in p.stdout:
            buf.append(redact(line.rstrip("\n")))
            if time.time() - last_save[0] > 2:
                last_save[0] = time.time()
                store.x("UPDATE agent_jobs SET output=?, updated=? WHERE id=?", ("\n".join(buf)[-20000:], time.time(), j["id"]))
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    deadline = time.time() + int(store.get("agents.timeout_min")) * 60
    while p.poll() is None:
        if j["id"] in _cancel:
            winapi.kill_pid(p.pid)
            break
        if time.time() > deadline:
            winapi.kill_pid(p.pid)
            buf.append("(stopped: agents.timeout_min exceeded)")
            break
        time.sleep(0.5)
    t.join(5)
    return p.returncode, "\n".join(buf)


def _run_claude_ui(j):
    from . import apps, uia, screen
    wins = apps.windows_of("claude")
    if not wins:
        raise RuntimeError("Claude desktop app is not open")
    hwnd = wins[0]["hwnd"]
    apps.focus("claude")
    time.sleep(0.6)
    before = ""
    try:
        before = uia.read_text(hwnd, 40000)
    except Exception:
        pass
    winapi.paste_text(f"[Working folder: {j['repo']}]\n{j['prompt']}")
    time.sleep(0.4)
    winapi.press("enter")
    last, stable_since = "", time.time()
    deadline = time.time() + int(store.get("agents.timeout_min")) * 60
    time.sleep(3)
    while time.time() < deadline and j["id"] not in _cancel:
        time.sleep(4)
        try:
            cur = uia.read_text(hwnd, 40000)
        except Exception:
            cur = last
        if cur != last:
            last, stable_since = cur, time.time()
        elif time.time() - stable_since > 25:
            break
    new = last.replace(before, "", 1) if before and before in last else last
    return 0, "(observed from the Claude window, not an API result)\n" + redact(new[-6000:])


def _run(jid):
    j = get(jid)
    before = _dirty(j["repo"])
    status, out = "failed", ""
    try:
        rc, out = _run_claude_ui(j) if j["agent"] == "claude" else _run_cli(j)
        status = "cancelled" if jid in _cancel else ("done" if rc == 0 else "failed")
        if status == "done" and ("no output produced" in out or not out.strip()):
            status = "failed"                                      # a clean exit that produced nothing is not a success
            out += "\n(Hukum: the agent exited without producing output - see the message above)"
        if rc not in (0, None) and status == "failed":
            out += f"\n(exit code {rc})"
    except Exception as e:
        out = f"{type(e).__name__}: {e}"
    after = _dirty(j["repo"])
    changed = sorted(after - before)
    verify_result = ""
    if status == "done" and j["verify"]:
        try:
            r = subprocess.run(j["verify"], shell=True, cwd=j["repo"], capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
            verify_result = ("PASS" if r.returncode == 0 else "FAIL") + "\n" + redact((r.stdout + r.stderr)[-1500:])
            if r.returncode != 0:
                status = "failed"
        except Exception as e:
            verify_result = f"FAIL (could not run): {e}"
            status = "failed"
    _set(jid, status=status, output=out[-20000:], files=changed, verify_result=verify_result)
    if j["task_id"]:
        try:
            from . import memory
            memory.update_task(j["task_id"], status="done" if status == "done" else "todo", result=f"{j['agent']}: {status}")
        except Exception:
            pass
    conflict = [f for f in changed if sum(1 for o in store.q("SELECT files FROM agent_jobs WHERE status='running' AND repo=?", (j["repo"],)) if f in o["files"])]
    notify.notify("info" if status == "done" else "warning", f"{j['agent']} {status}: {j['prompt'][:60]}",
                  f"Observed: job #{jid} {status}; {len(changed)} file(s) changed" + (f"; verification {verify_result.splitlines()[0]}" if verify_result else "")
                  + (f"; possible conflicts: {conflict}" if conflict else ""), key=f"agent:{jid}", source="agents", force=True)
    _procs.pop(jid, None)
    _cancel.discard(jid)
    _wake.set()
