"""System health: CPU, RAM, GPU, disks, battery, network, processes, with a history ring buffer saved to the database."""
import threading
import time

from . import winapi, store

_last_net = {"t": 0, "rx": 0, "tx": 0}
_hist = []
_lock = threading.Lock()


def sample():
    cpu = winapi.cpu_percent()
    mem = winapi.memory()
    gpu = winapi.gpu()
    net = winapi.net_counters()
    now = time.time()
    down = up = 0.0
    if net and _last_net["t"]:
        dt = max(now - _last_net["t"], 0.001)
        down, up = max(net[0] - _last_net["rx"], 0) / dt, max(net[1] - _last_net["tx"], 0) / dt
    if net:
        _last_net.update(t=now, rx=net[0], tx=net[1])
    bat = winapi.battery()
    drives = winapi.drives()
    s = {"ts": now, "cpu": round(cpu, 1), "ram": mem["percent"], "ram_used": mem["used"], "ram_total": mem["total"],
         "gpu": gpu["util"] if gpu else None, "gpu_temp": gpu["temp"] if gpu else None,
         "gpu_mem": [gpu["mem_used"], gpu["mem_total"]] if gpu else None, "gpu_name": gpu["name"] if gpu else None,
         "disk": max((d["percent"] for d in drives), default=None), "drives": drives,
         "net_down": round(down), "net_up": round(up), "battery": bat}
    with _lock:
        _hist.append(s)
        del _hist[:-720]
    return s


def record():
    s = sample()
    try:
        store.x("INSERT OR REPLACE INTO sysmon(ts,cpu,ram,gpu,disk,net_down,net_up,battery) VALUES(?,?,?,?,?,?,?,?)",
                (s["ts"], s["cpu"], s["ram"], s["gpu"] or 0, s["disk"] or 0, s["net_down"], s["net_up"], (s["battery"] or {}).get("percent", -1)))
    except Exception:
        pass
    return s


def history(seconds=900):
    cut = time.time() - seconds
    with _lock:
        mem = [h for h in _hist if h["ts"] >= cut]
    if len(mem) >= 5:
        return [{"ts": h["ts"], "cpu": h["cpu"], "ram": h["ram"], "gpu": h["gpu"], "net_down": h["net_down"], "net_up": h["net_up"]} for h in mem]
    rows = store.q("SELECT ts,cpu,ram,gpu,net_down,net_up FROM sysmon WHERE ts>=? ORDER BY ts", (cut,))
    return rows


def top_processes(by="cpu", n=8):
    procs = winapi.processes()
    agg = {}
    for p in procs:
        a = agg.setdefault(p["name"], {"name": p["name"], "pids": [], "cpu": 0.0, "mem": 0})
        a["pids"].append(p["pid"])
        a["cpu"] += p["cpu"]
        a["mem"] += p["mem"]
    rows = [r for r in agg.values() if r["name"] not in ("System Idle Process", "System", "Registry")]
    rows.sort(key=lambda r: -(r["cpu"] if by == "cpu" else r["mem"]))
    return [{"name": r["name"], "count": len(r["pids"]), "cpu": round(r["cpu"], 1), "mem_mb": round(r["mem"] / 1048576), "pid": r["pids"][0]}
            for r in rows[:n]]


def describe(s=None):
    """One plain-language paragraph about the machine, from real numbers."""
    s = s or sample()
    gb = lambda b: f"{b / 2**30:.1f} GB"
    parts = [f"CPU {s['cpu']:.0f}%", f"RAM {s['ram']:.0f}% ({gb(s['ram_used'])} of {gb(s['ram_total'])})"]
    if s["gpu"] is not None:
        parts.append(f"GPU {s['gpu']:.0f}% at {s['gpu_temp']:.0f}°C, {s['gpu_mem'][0]:.0f} of {s['gpu_mem'][1]:.0f} MiB used")
    for d in s["drives"]:
        parts.append(f"{d['path']} {100 - d['percent']:.0f}% free ({gb(d['free'])})")
    if s["battery"]:
        parts.append(f"battery {s['battery']['percent']}%" + (" charging" if s["battery"]["charging"] else " on battery"))
    return ", ".join(parts)


def diagnose(s=None):
    """Why might the PC feel slow? Findings from real numbers (used by 'why is my laptop slow')."""
    s = s or sample()
    out = []
    if s["ram"] >= 88:
        top = top_processes("mem", 3)
        out.append(f"RAM is {s['ram']:.0f}% full; biggest users: " + ", ".join(f"{t['name']} ({t['mem_mb']} MB)" for t in top))
    if s["cpu"] >= 80:
        top = top_processes("cpu", 3)
        out.append(f"CPU is at {s['cpu']:.0f}%; busiest: " + ", ".join(f"{t['name']} ({t['cpu']}%)" for t in top))
    for d in s["drives"]:
        if d["percent"] >= 92:
            out.append(f"Drive {d['path']} is {d['percent']:.0f}% full")
    if s["battery"] and not s["battery"]["charging"] and s["battery"]["percent"] <= 20:
        out.append(f"Battery is low ({s['battery']['percent']}%) and not charging")
    if s["gpu"] is not None and s["gpu_temp"] and s["gpu_temp"] >= 85:
        out.append(f"GPU is hot ({s['gpu_temp']:.0f}°C)")
    return out or ["Nothing alarming: CPU, RAM, disks and battery look normal."]


_thread = None
_stop = threading.Event()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        n = 0
        while not _stop.is_set():
            try:
                if winapi.cpu_percent() < 100:
                    s = record() if n % 6 == 0 else sample()
                n += 1
            except Exception:
                pass
            _stop.wait(max(1, int(store.get("system.history_s"))))
    _stop.clear()
    _thread = threading.Thread(target=loop, daemon=True, name="sysmon")
    _thread.start()


def stop():
    _stop.set()
