"""Application registry: known profiles (Antigravity, Claude, Codex, VS Code, browsers, terminals ...) plus every
installed Start-menu app, with running state, launch/focus/close and verification of each step."""
import os
import re
import subprocess
import time

from . import winapi, store
from .pshost import host, as_list

LA = os.environ.get("LOCALAPPDATA", "")
PF = os.environ.get("ProgramFiles", r"C:\Program Files")

PROFILES = [
    # id, name, kind, process names (no .exe), exe path hints, launch exe, start-menu AppID, folder-open argv template
    dict(id="antigravity", name="Google Antigravity", kind="coding-agent", procs=["Antigravity IDE", "Antigravity"],
         hints=["antigravity"], exe=os.path.join(LA, "Programs", "Antigravity IDE", "Antigravity IDE.exe"),
         appid="Google.AntigravityIDE", open=["{exe}", "{path}"]),
    dict(id="claude", name="Claude Desktop", kind="coding-agent", procs=["Claude"], hints=["windowsapps\\claude_", "anthropic"],
         exe="", appid="Claude_pzs8sxrjxfjjc!Claude", open=None),
    dict(id="codex", name="OpenAI Codex", kind="coding-agent", procs=["Codex", "ChatGPT"], hints=["openai.codex"],
         exe="", appid="OpenAI.Codex_2p2nqsd0c76g0!App", open=None),
    dict(id="vscode", name="Visual Studio Code", kind="editor", procs=["Code"], hints=["microsoft vs code"],
         exe=os.path.join(LA, "Programs", "Microsoft VS Code", "Code.exe"), appid="Microsoft.VisualStudioCode", open=["{exe}", "{path}"]),
    dict(id="chrome", name="Google Chrome", kind="browser", procs=["chrome"], hints=["google\\chrome"],
         exe=os.path.join(PF, "Google", "Chrome", "Application", "chrome.exe"), appid="Chrome", open=["{exe}", "{path}"]),
    dict(id="edge", name="Microsoft Edge", kind="browser", procs=["msedge"], hints=["edge"],
         exe=os.path.join(os.environ.get("ProgramFiles(x86)", PF), "Microsoft", "Edge", "Application", "msedge.exe"),
         appid="MSEdge", open=["{exe}", "{path}"]),
    dict(id="terminal", name="Windows Terminal", kind="terminal", procs=["WindowsTerminal", "wt"], hints=["windowsterminal"],
         exe="", appid="Microsoft.WindowsTerminal_8wekyb3d8bbwe!App", open=["wt.exe", "-d", "{path}"]),
    dict(id="powershell", name="PowerShell", kind="terminal", procs=["powershell", "pwsh"], hints=[], exe="powershell.exe", appid="",
         open=["cmd.exe", "/c", "start", "powershell", "-NoExit", "-Command", "Set-Location -LiteralPath '{path}'"]),
    dict(id="cmd", name="Command Prompt", kind="terminal", procs=["cmd"], hints=[], exe="cmd.exe", appid="",
         open=["cmd.exe", "/c", "start", "cmd", "/k", "cd /d {path}"]),
    dict(id="explorer", name="File Explorer", kind="utility", procs=["explorer"], hints=[], exe="explorer.exe", appid="", open=["explorer.exe", "{path}"]),
    dict(id="taskmgr", name="Task Manager", kind="utility", procs=["Taskmgr"], hints=[], exe="taskmgr.exe", appid="", open=None),
    dict(id="notepad", name="Notepad", kind="utility", procs=["notepad"], hints=[], exe="notepad.exe", appid="", open=["notepad.exe", "{path}"]),
]
_by_id = {p["id"]: p for p in PROFILES}
_startapps = {"ts": 0, "apps": []}
_last_seen = {}                # app id -> unix time of last observed activity (updated by the monitor and by commands)


def start_apps(refresh=False):
    """Installed apps from the Start menu: [{name, appid}] (cached 10 minutes)."""
    if refresh or time.time() - _startapps["ts"] > 600 or not _startapps["apps"]:
        try:
            r = as_list(host.run("Get-StartApps | ForEach-Object { @{name=$_.Name; appid=$_.AppID} }", timeout=40))
            _startapps.update(ts=time.time(), apps=[{"name": a["name"], "appid": a["appid"]} for a in r])
        except Exception:
            pass
    return _startapps["apps"]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def resolve(name):
    """Profile (or a Start-menu app wrapped as a profile) best matching a spoken/typed name; None if unknown."""
    n = _norm(name)
    if not n:
        return None
    if name in _by_id:
        return _by_id[name]
    for p in PROFILES:                                   # exact id/name/process
        if n in (_norm(p["id"]), _norm(p["name"])) or n in [_norm(x) for x in p["procs"]]:
            return p
    aliases = {"vs code": "vscode", "code": "vscode", "visual studio code": "vscode", "agy": "antigravity", "chatgpt": "codex",
               "claude desktop": "claude", "google chrome": "chrome", "browser": "chrome", "wt": "terminal", "windows terminal": "terminal",
               "task manager": "taskmgr", "files": "explorer", "file explorer": "explorer", "command prompt": "cmd", "terminal": "terminal"}
    if n in aliases:
        return _by_id[aliases[n]]
    for p in PROFILES:                                   # partial
        if n in _norm(p["name"]) or _norm(p["id"]) in n.split():
            return p
    for a in start_apps():                               # any installed app
        if n == _norm(a["name"]) or n in _norm(a["name"]):
            return dict(id="app:" + _norm(a["name"]).replace(" ", "-"), name=a["name"], kind="app", procs=[a["name"]], hints=[],
                        exe="", appid=a["appid"], open=None)
    return None


def _proc_match(p, procs, windows_by_pid=None):
    name = os.path.splitext(os.path.basename(p.get("exe") or p.get("name") or ""))[0].lower()
    return name in [x.lower() for x in p["procs"]] or any(h in (p.get("exe") or "").lower() for h in p["hints"])


def windows_of(profile):
    out = []
    for w in winapi.list_windows():
        exe_l = (w["exe"] or "").lower()
        if w["name"].lower() in [x.lower() for x in profile["procs"]] or any(h in exe_l for h in profile["hints"] if h):
            out.append(w)
    return out


def status(profile_id=None):
    """Every known app with running state. Also marks activity (title change) for last_activity."""
    wins = winapi.list_windows()
    procs = winapi.processes()
    out = []
    for p in PROFILES:
        if profile_id and p["id"] != profile_id:
            continue
        pw = [w for w in wins if w["name"].lower() in [x.lower() for x in p["procs"]] or any(h in (w["exe"] or "").lower() for h in p["hints"] if h)]
        names = [x.lower() + ".exe" for x in p["procs"]]
        pp = [q for q in procs if q["name"].lower() in names]
        running = bool(pw or pp)
        fgw = next((w for w in pw if w.get("foreground")), None)
        if pw:
            _last_seen[p["id"]] = max(_last_seen.get(p["id"], 0), time.time() if fgw else _last_seen.get(p["id"], 0))
        out.append({"id": p["id"], "name": p["name"], "kind": p["kind"], "running": running, "foreground": bool(fgw),
                    "windows": [{"hwnd": w["hwnd"], "title": w["title"], "minimized": w["minimized"]} for w in pw][:6],
                    "active_window": (fgw or (pw[0] if pw else {})).get("title", ""),
                    "cpu": round(sum(q["cpu"] for q in pp), 1), "mem_mb": round(sum(q["mem"] for q in pp) / 1048576),
                    "last_activity": _last_seen.get(p["id"]) or None, "launchable": bool(p["exe"] and os.path.exists(p["exe"]) or p["appid"] or p["exe"]),
                    "monitored": p["procs"][0].lower() in [x.lower() for x in store.get_list("monitor.apps")]})
    return out


def touch(profile_id):
    _last_seen[profile_id] = time.time()


def _spawn(argv):
    return subprocess.Popen(argv, creationflags=0x00000008 | 0x00000200, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch(name, path=None, wait=15):
    """Start an app (optionally opening a folder/file/URL). Verified: returns only after a window of it appears."""
    prof = resolve(name)
    if not prof:
        raise LookupError(f"I don't know an app called '{name}'")
    before = {w["hwnd"] for w in windows_of(prof)}
    exe = prof["exe"] if prof["exe"] and (os.path.isabs(prof["exe"]) is False or os.path.exists(prof["exe"])) else ""
    if path and prof.get("open"):
        argv = [x.replace("{exe}", exe or prof["procs"][0]).replace("{path}", str(path)) for x in prof["open"]]
        _spawn(argv)
    elif exe:
        _spawn([exe] + ([str(path)] if path else []))
    elif prof["appid"]:
        _spawn(["explorer.exe", "shell:AppsFolder\\" + prof["appid"]])
    else:
        _spawn(["cmd.exe", "/c", "start", "", prof["procs"][0]])
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.4)
        now = windows_of(prof)
        fresh = [w for w in now if w["hwnd"] not in before]
        if fresh or (before and now):
            w = (fresh or now)[0]
            touch(prof["id"])
            return {"app": prof["name"], "id": prof["id"], "hwnd": w["hwnd"], "title": w["title"], "new_window": bool(fresh),
                    "verified": True}
    raise TimeoutError(f"{prof['name']} was started but no window appeared within {wait}s")


def focus(name=None, hwnd=None, title=None):
    """Bring an app's window to the front. Verified against the real foreground window."""
    target = None
    if hwnd:
        target = winapi.window_info(hwnd)
    elif title:
        t = title.lower()
        cands = [w for w in winapi.list_windows() if t in w["title"].lower()]
        target = cands[0] if cands else None
    elif name:
        prof = resolve(name)
        if not prof:
            raise LookupError(f"I don't know an app called '{name}'")
        ws = windows_of(prof)
        ws.sort(key=lambda w: (not w.get("foreground"), w["minimized"]))
        target = ws[0] if ws else None
        if not target:
            raise LookupError(f"{prof['name']} has no open window")
    if not target:
        raise LookupError("no matching window")
    ok = winapi.focus(target["hwnd"])
    fg = winapi.foreground() or {}
    if not ok:
        raise RuntimeError(f"Windows refused to bring '{target['title']}' to the front")
    for p in PROFILES:
        if target["name"].lower() in [x.lower() for x in p["procs"]]:
            touch(p["id"])
    return {"title": target["title"], "hwnd": target["hwnd"], "foreground_now": fg.get("title", ""), "verified": True}


def close(name=None, hwnd=None, wait=5):
    """Ask windows to close (WM_CLOSE: the app may ask to save). Reports what is left; never force-kills."""
    if hwnd:
        ws = [winapi.window_info(hwnd)]
    else:
        prof = resolve(name)
        if not prof:
            raise LookupError(f"I don't know an app called '{name}'")
        ws = windows_of(prof)
    if not ws:
        return {"closed": 0, "remaining": 0, "note": "nothing was open"}
    for w in ws:
        winapi.close_window(w["hwnd"])
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.3)
        left = [w for w in ws if winapi.is_window(w["hwnd"])]
        if not left:
            break
    left = [w for w in ws if winapi.is_window(w["hwnd"])]
    note = ""
    if left:
        from . import uia
        dl = []
        for w in left:
            dl += uia.dialogs(w["pid"])
        if dl:
            note = "The app is asking something: " + "; ".join(f"'{d['title']}' [{', '.join(d['buttons'])}]" for d in dl)
        else:
            note = "Some windows are still open (the app may be busy)"
    return {"closed": len(ws) - len(left), "remaining": len(left), "note": note}
