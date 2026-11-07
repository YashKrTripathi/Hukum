"""Project intelligence: finds git projects inside the allowed folders, reads their language/framework/scripts/ports,
git state and env KEY NAMES (never values), and spots running dev servers (listening ports + their project)."""
import json
import os
import re
import subprocess
import threading
import time

from . import store, winapi

SKIP = {"node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target", "data"}
_scan_lock = threading.Lock()


def _git(path, *args, timeout=15):
    try:
        r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _read(path, limit=200000):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except Exception:
        return ""


def _roots():
    return [r for r in store.get_list("folders.allowed") if os.path.isdir(r)]


def find_dirs(depth=3):
    """Directories that look like projects (git repo or has a manifest) up to `depth` levels below the allowed roots."""
    found = []
    markers = ("package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "Cargo.toml", "go.mod", "composer.json", "index.html")
    for root in _roots():
        root = os.path.abspath(root)
        base = root.count(os.sep)
        weak = []
        for cur, dirs, files in os.walk(root):
            real = ".git" in dirs or ".git" in files or any(m in files for m in markers[:-1])
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            nested_weak = any(cur.startswith(f + os.sep) for f in weak)
            weakish = (any(f.endswith(".py") for f in files) or "README.md" in files) and not nested_weak
            if real:
                found.append(cur)
            elif weakish and cur.count(os.sep) - base in (0, 1):
                found.append(cur)
                weak.append(cur)
            if cur.count(os.sep) - base >= depth:
                dirs[:] = []
    return sorted(set(found))


def analyse(path):
    """Everything useful about one project directory."""
    info = {"path": path, "name": os.path.basename(path), "languages": [], "frameworks": [], "scripts": {}, "ports": [], "env_keys": [],
            "git": None, "docs": [], "tests": False, "entry": ""}
    names = set(os.listdir(path))
    pkg = {}
    if "package.json" in names:
        try:
            pkg = json.loads(_read(os.path.join(path, "package.json")) or "{}")
        except Exception:
            pkg = {}
        info["languages"].append("JavaScript/TypeScript" if "tsconfig.json" in names else "JavaScript")
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        for dep, fw in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"), ("express", "Express"), ("vite", "Vite"),
                        ("@angular/core", "Angular"), ("nestjs", "NestJS"), ("electron", "Electron"), ("react-native", "React Native"), ("tailwindcss", "Tailwind")):
            if dep in deps:
                info["frameworks"].append(fw)
        info["scripts"] = pkg.get("scripts", {})
        info["tests"] = "test" in info["scripts"]
    py = [n for n in ("requirements.txt", "pyproject.toml", "setup.py") if n in names]
    pyfiles = [n for n in names if n.endswith(".py")]
    if py or pyfiles:
        info["languages"].append("Python")
        txt = (_read(os.path.join(path, "requirements.txt")) + _read(os.path.join(path, "pyproject.toml"))).lower()
        for dep, fw in (("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI"), ("streamlit", "Streamlit"), ("pytest", "pytest")):
            if dep in txt:
                info["frameworks"].append(fw)
        info["tests"] = info["tests"] or "tests" in names or "pytest" in txt
        for e in ("main.py", "app.py", "server.py", "manage.py", "webserver.py"):
            if e in names:
                info["entry"] = e
                break
    for marker, lang in (("pom.xml", "Java"), ("build.gradle", "Java/Kotlin"), ("Cargo.toml", "Rust"), ("go.mod", "Go"), ("composer.json", "PHP")):
        if marker in names:
            info["languages"].append(lang)
    if "Dockerfile" in names or "docker-compose.yml" in names:
        info["frameworks"].append("Docker")
    info["docs"] = [n for n in names if n.lower() in ("readme.md", "claude.md", "agents.md", "contributing.md")]
    # ports mentioned in scripts / env / common config
    blob = " ".join(map(str, info["scripts"].values())) + _read(os.path.join(path, ".env.example"), 4000)
    ports = set(int(m) for m in re.findall(r"(?:--port[= ]|PORT[= :]+|localhost:)(\d{3,5})", blob))
    for e in ("webserver.py", "server.py", "app.py", "main.py"):
        if e in names:
            ports |= set(int(m) for m in re.findall(r"port\W{0,4}(\d{4,5})", _read(os.path.join(path, e), 30000), re.I)[:4])
    info["ports"] = sorted(p for p in ports if 1024 <= p <= 65535)
    # env KEY NAMES only
    for ef in (".env", ".env.example", ".env.local"):
        t = _read(os.path.join(path, ef), 20000)
        for ln in t.splitlines():
            m = re.match(r"\s*([A-Z][A-Z0-9_]{2,})\s*=", ln)
            if m and m[1] not in info["env_keys"]:
                info["env_keys"].append(m[1])
    if ".git" in names:
        branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
        status = _git(path, "status", "--porcelain")
        changed = [ln[3:] for ln in status.splitlines()][:50]
        last = _git(path, "log", "-1", "--format=%h|%an|%ar|%s")
        ahead = _git(path, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        remote = re.sub(r"//[^/@]+@", "//", _git(path, "remote", "get-url", "origin"))
        info["git"] = {"branch": branch, "dirty": len(changed), "changed": changed, "remote": remote, "last_commit": last,
                       "behind_ahead": ahead.split() if ahead else None}
    info["languages"] = list(dict.fromkeys(info["languages"]))
    info["frameworks"] = list(dict.fromkeys(info["frameworks"]))
    return info


def scan(force=False):
    """Rescan all projects and store them. Returns the list."""
    if not _scan_lock.acquire(blocking=False):
        return list_projects()
    try:
        out = []
        for d in find_dirs():
            try:
                info = analyse(d)
            except Exception as e:
                info = {"path": d, "name": os.path.basename(d), "error": str(e)[:100]}
            store.x("INSERT OR REPLACE INTO projects(path,name,data,scanned) VALUES(?,?,?,?)", (d, info["name"], json.dumps(info), time.time()))
            out.append(info)
        keep = {i["path"] for i in out}
        for r in store.q("SELECT path FROM projects"):
            if r["path"] not in keep:
                store.x("DELETE FROM projects WHERE path=?", (r["path"],))
        return out
    finally:
        _scan_lock.release()


def list_projects():
    return [json.loads(r["data"]) for r in store.q("SELECT data FROM projects ORDER BY name")]


def get(name_or_path):
    s = str(name_or_path).lower().strip()
    best = None
    for p in list_projects():
        if p["path"].lower() == s or p["name"].lower() == s:
            return p
        if s and s in p["name"].lower() and not best:
            best = p
    return best


def refresh(path):
    info = analyse(path)
    store.x("INSERT OR REPLACE INTO projects(path,name,data,scanned) VALUES(?,?,?,?)", (path, info["name"], json.dumps(info), time.time()))
    return info


def _listening():
    """{pid: [ports]} of TCP listeners (from netstat)."""
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10, creationflags=0x08000000)
    except Exception:
        return {}
    out = {}
    for ln in r.stdout.splitlines():
        p = ln.split()
        if len(p) >= 5 and p[3] == "LISTENING":
            try:
                port = int(p[1].rsplit(":", 1)[1])
                out.setdefault(int(p[4]), []).append(port)
            except Exception:
                pass
    return out


def _cwd_hint(pid_name_cmd, projects):
    low = pid_name_cmd.lower()
    for p in projects:
        if p["path"].lower() in low or p["name"].lower() in low:
            return p["name"]
    return ""


def dev_servers():
    """Processes that listen on a port and look like development servers (node/python/java/php/dotnet/go...), with project guess."""
    listen = _listening()
    projects = list_projects()
    procs = {p["pid"]: p for p in winapi.processes(with_cpu=False)}
    dev = {"node.exe", "python.exe", "pythonw.exe", "py.exe", "java.exe", "php.exe", "dotnet.exe", "deno.exe", "bun.exe", "ruby.exe",
           "ollama.exe", "uvicorn.exe", "nginx.exe", "httpd.exe", "mysqld.exe", "postgres.exe", "mongod.exe", "redis-server.exe"}
    out = []
    for pid, ports in listen.items():
        pr = procs.get(pid)
        if not pr or pr["name"].lower() not in dev:
            continue
        cmd = _cmdline(pid)
        proj = _cwd_hint(cmd, projects)
        if not proj:
            for p in projects:
                if set(p.get("ports") or []) & set(ports):
                    proj = p["name"]
                    break
        out.append({"pid": pid, "name": pr["name"], "ports": sorted(set(ports)), "cmd": cmd[:200], "project": proj, "mem_mb": round(pr["mem"] / 1048576)})
    return sorted(out, key=lambda s: s["ports"][0])


def _cmdline(pid):
    try:
        from . import pshost
        r = pshost.host.run("(Get-CimInstance Win32_Process -Filter \"ProcessId=$($P.pid)\").CommandLine", {"pid": int(pid)}, timeout=15)
        return str(r or "")
    except Exception:
        return ""


def summary(p):
    bits = [p["name"]]
    if p.get("languages"):
        bits.append("/".join(p["languages"]))
    if p.get("frameworks"):
        bits.append(", ".join(p["frameworks"]))
    g = p.get("git")
    if g:
        bits.append(f"branch {g['branch']}" + (f", {g['dirty']} changed" if g["dirty"] else ", clean"))
    return " - ".join(bits)


def scan_loop():
    def run():
        while True:
            try:
                scan()
            except Exception:
                pass
            time.sleep(int(store.get("project.scan_minutes")) * 60)
    threading.Thread(target=run, daemon=True, name="project-scan").start()
