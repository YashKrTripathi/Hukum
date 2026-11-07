"""Windows desktop primitives through ctypes (no third-party packages): windows, focus, keyboard, mouse, clipboard,
processes and system counters. Everything here is mechanical; permission checks happen one layer up."""
import ctypes
import os
import re
import subprocess
import sys
import time

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi")
    HWND = wintypes.HWND
    user32.GetForegroundWindow.restype = HWND
    user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [HWND]
    user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [HWND]
    user32.IsIconic.argtypes = [HWND]
    user32.IsZoomed.argtypes = [HWND]
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [HWND]
    user32.BringWindowToTop.argtypes = [HWND]
    user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.MoveWindow.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
    user32.IsWindow.argtypes = [HWND]
    user32.GetAncestor.argtypes = [HWND, wintypes.UINT]
    user32.GetAncestor.restype = HWND
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
    try:                                   # real pixels everywhere: screenshots, OCR and clicks must agree with UI Automation
        user32.SetProcessDPIAware()
    except Exception:
        pass

SW_RESTORE, SW_MINIMIZE, SW_MAXIMIZE = 9, 6, 3
WM_CLOSE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED = 0x1000


def _need_win():
    if not IS_WIN:
        raise OSError("this needs Windows")


# ---------------------------------------------------------------- processes / windows
def exe_of(pid):
    _need_win()
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def _title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd):
    v = wintypes.DWORD(0)
    try:
        dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        return False
    return bool(v.value)


def window_info(hwnd):
    _need_win()
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = exe_of(pid.value)
    return {"hwnd": int(hwnd or 0), "title": _title(hwnd), "pid": pid.value, "exe": exe,
            "name": os.path.splitext(os.path.basename(exe))[0] if exe else "", "cls": _class(hwnd),
            "rect": [r.left, r.top, r.right, r.bottom], "minimized": bool(user32.IsIconic(hwnd)),
            "maximized": bool(user32.IsZoomed(hwnd))}


def list_windows():
    """Top-level windows a user would see in Alt+Tab."""
    _need_win()
    out = []
    fg = int(user32.GetForegroundWindow() or 0)

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
                return True
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            if not user32.GetWindowTextLengthW(hwnd):
                return True
            info = window_info(hwnd)
            if info["cls"] in ("Progman", "Shell_TrayWnd") or not info["exe"]:
                return True
            info["foreground"] = info["hwnd"] == fg
            out.append(info)
        except Exception:
            pass
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def foreground():
    _need_win()
    h = user32.GetForegroundWindow()
    return window_info(h) if h else None


def is_window(hwnd):
    return bool(IS_WIN and user32.IsWindow(hwnd))


def focus(hwnd):
    """Bring a window to the front. Returns True only if it is verifiably the foreground window afterwards."""
    _need_win()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    def verified():
        for _ in range(10):
            time.sleep(0.05)
            cur = user32.GetForegroundWindow()
            if cur and (int(cur) == int(hwnd) or int(user32.GetAncestor(cur, 3) or 0) == int(hwnd)):
                return True
        return False

    # attach to the input queues of the current foreground window and the target: this satisfies Windows'
    # foreground lock without pressing any key (a lone ALT tap would put the target into menu mode)
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    my = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tg_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached = [t for t in {fg_tid, tg_tid} if t and t != my and user32.AttachThreadInput(my, t, True)]
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for t in attached:
            user32.AttachThreadInput(my, t, False)
    if verified():
        return True
    # last resort: ALT + an unassigned key + ALT (no menu activation) unlocks SetForegroundWindow
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0xE8, 0, 0, 0)
    user32.keybd_event(0xE8, 0, 2, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return verified()


def show(hwnd, how):
    _need_win()
    user32.ShowWindow(hwnd, {"minimize": SW_MINIMIZE, "maximize": SW_MAXIMIZE, "restore": SW_RESTORE}[how])


def close_window(hwnd):
    _need_win()
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def move_window(hwnd, x, y, w, h):
    _need_win()
    user32.MoveWindow(hwnd, int(x), int(y), int(w), int(h), True)


def monitors():
    _need_win()
    mons = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rect, lp):
        r = rect.contents
        mons.append({"rect": [r.left, r.top, r.right, r.bottom], "w": r.right - r.left, "h": r.bottom - r.top})
        return True
    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    return mons


# ---------------------------------------------------------------- keyboard / mouse
class _MOUSEINPUT(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4
VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B, "enter": 0x0D, "return": 0x0D,
      "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
      "insert": 0x2D, "capslock": 0x14}
for _i in range(1, 13):
    VK[f"f{_i}"] = 0x6F + _i


def _send(inputs):
    arr = (_INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
    if n != len(inputs):
        raise OSError("SendInput was blocked (is the target window elevated?)")


def _key(vk=0, scan=0, flags=0):
    i = _INPUT(type=1)
    i.u.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return i


def type_text(text, delay=0.004):
    """Type unicode text into whatever has focus."""
    _need_win()
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            _send([_key(VK["enter"]), _key(VK["enter"], flags=KEYEVENTF_KEYUP)])
        else:
            code = ord(ch)
            units = [code] if code < 0x10000 else [0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF)]
            ev = []
            for u in units:
                ev += [_key(0, u, KEYEVENTF_UNICODE), _key(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
            _send(ev)
        if delay:
            time.sleep(delay)


def _vk_for(name):
    n = name.strip().lower()
    if n in VK:
        return VK[n]
    if len(n) == 1:
        r = user32.VkKeyScanW(ord(n))
        if r == -1:
            raise ValueError(f"cannot press '{name}'")
        return r & 0xFF
    raise ValueError(f"unknown key '{name}'")


def press(combo):
    """'ctrl+s', 'alt+tab', 'enter', 'ctrl+shift+esc'."""
    _need_win()
    keys = [_vk_for(k) for k in re.split(r"\+", combo) if k.strip()]
    if not keys:
        raise ValueError("empty key combination")
    down = [_key(k) for k in keys]
    up = [_key(k, flags=KEYEVENTF_KEYUP) for k in reversed(keys)]
    _send(down + up)


def cursor_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def mouse_click(x, y, button="left", double=False):
    _need_win()
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    d, u = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}[button]
    ev = []
    for _ in range(2 if double else 1):
        for f in (d, u):
            i = _INPUT(type=0)
            i.u.mi = _MOUSEINPUT(0, 0, 0, f, 0, 0)
            ev.append(i)
    _send(ev)


def mouse_scroll(clicks):
    i = _INPUT(type=0)
    i.u.mi = _MOUSEINPUT(0, 0, ctypes.c_ulong(int(clicks * 120) & 0xFFFFFFFF).value, 0x800, 0, 0)
    _send([i])


# ---------------------------------------------------------------- clipboard
CF_UNICODETEXT = 13


def clipboard_get():
    _need_win()
    user32.OpenClipboard.argtypes = [HWND]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set(text):
    _need_win()
    user32.OpenClipboard.argtypes = [HWND]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        raise OSError("clipboard busy")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x2, len(data))          # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def paste_text(text):
    """Put text on the clipboard, press Ctrl+V, then restore what was there before."""
    old = clipboard_get()
    clipboard_set(text)
    time.sleep(0.05)
    press("ctrl+v")
    time.sleep(0.15)
    if old is not None:
        clipboard_set(old)


# ---------------------------------------------------------------- system counters
class _MEMSTAT(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    _need_win()
    m = _MEMSTAT()
    m.dwLength = ctypes.sizeof(m)
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"percent": float(m.dwMemoryLoad), "total": m.ullTotalPhys, "available": m.ullAvailPhys,
            "used": m.ullTotalPhys - m.ullAvailPhys}


def _ft(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


_last_cpu = {}


def cpu_percent():
    """System-wide CPU use since the previous call."""
    _need_win()
    idle, kern, usr = (wintypes.FILETIME() for _ in range(3))
    kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(usr))
    i, k, u = _ft(idle), _ft(kern), _ft(usr)
    prev = _last_cpu.get("sys")
    _last_cpu["sys"] = (i, k, u)
    if not prev:
        time.sleep(0.2)
        return cpu_percent()
    di, dk, du = i - prev[0], k - prev[1], u - prev[2]
    total = dk + du
    return max(0.0, min(100.0, 100.0 * (total - di) / total)) if total else 0.0


def disk_usage(path="C:\\"):
    _need_win()
    free, total, tf = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    ok = kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(path), ctypes.byref(free), ctypes.byref(total), ctypes.byref(tf))
    if not ok:
        return None
    return {"path": path, "total": total.value, "free": free.value, "percent": 100.0 * (total.value - free.value) / total.value}


def drives():
    _need_win()
    mask = kernel32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3:       # fixed disks
                d = disk_usage(root)
                if d:
                    out.append(d)
    return out


class _POWER(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                    ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def battery():
    _need_win()
    p = _POWER()
    kernel32.GetSystemPowerStatus(ctypes.byref(p))
    if p.BatteryFlag == 128 or p.BatteryLifePercent == 255:
        return None
    return {"percent": p.BatteryLifePercent, "charging": bool(p.ACLineStatus == 1), "plugged": p.ACLineStatus == 1}


def net_counters():
    """(bytes_received, bytes_sent) over all interfaces, from `netstat -e`."""
    try:
        out = subprocess.run(["netstat", "-e"], capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout
        for line in out.splitlines():
            if line.strip().lower().startswith("bytes"):
                nums = [int(x) for x in re.findall(r"\d+", line)]
                return nums[0], nums[1]
    except Exception:
        pass
    return None


def internet_ok(host="1.1.1.1", port=53, timeout=1.5):
    import socket
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


# process list via ToolHelp + working set + cpu times
class _PROCENTRY(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]


class _PMC(ctypes.Structure if IS_WIN else object):
    if IS_WIN:
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]


_proc_cpu = {}


def processes(with_cpu=True):
    """[{pid, ppid, name, mem (bytes), cpu (% of one core since last call)}]"""
    _need_win()
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCENTRY)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCENTRY)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    out = []
    now = time.time()
    try:
        e = _PROCENTRY()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            pid = e.th32ProcessID
            mem, cpu = 0, 0.0
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid) if pid else None
            if h:
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(pmc)
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    mem = pmc.WorkingSetSize
                if with_cpu:
                    c, ex, k, u = (wintypes.FILETIME() for _ in range(4))
                    if kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(ex), ctypes.byref(k), ctypes.byref(u)):
                        total = _ft(k) + _ft(u)
                        prev = _proc_cpu.get(pid)
                        _proc_cpu[pid] = (total, now)
                        if prev and now > prev[1]:
                            cpu = 100.0 * ((total - prev[0]) / 1e7) / (now - prev[1])
                kernel32.CloseHandle(h)
            out.append({"pid": pid, "ppid": e.th32ParentProcessID, "name": e.szExeFile, "mem": mem, "cpu": round(max(cpu, 0.0), 1)})
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


def kill_pid(pid):
    _need_win()
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, creationflags=0x08000000)


def gpu():
    """NVIDIA GPU stats through nvidia-smi, or None."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout
        f = [x.strip() for x in out.strip().splitlines()[0].split(",")]
        return {"name": f[0], "util": float(f[1]), "temp": float(f[2]), "mem_used": float(f[3]), "mem_total": float(f[4]),
                "power": float(f[5]) if f[5].replace('.', '').isdigit() else None}
    except Exception:
        return None
