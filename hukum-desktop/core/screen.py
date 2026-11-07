"""Screen capture (GDI, no packages), PNG encoding, OCR (Windows.Media.Ocr through the PowerShell host) and the
privacy rules for what may be captured. Captures are per WINDOW, never the whole desktop, and nothing is captured
for excluded programs or sensitive-looking window titles."""
import ctypes
import hashlib
import os
import struct
import sys
import time
import zlib

from . import store, winapi
from .redact import redact

if winapi.IS_WIN:
    from ctypes import wintypes
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = winapi.user32
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

SHOTS_DIR = os.path.join(store.DATA_DIR, "shots")


class Blocked(Exception):
    """Capture refused for privacy reasons."""


def check_allowed(info):
    """Raise Blocked if this window must not be captured."""
    if not store.get("perm.screen"):
        raise Blocked("screen access is off in Settings")
    name = (info.get("name") or "").lower()
    title = (info.get("title") or "").lower()
    for ex in store.get_list("monitor.exclude"):
        if ex.lower() in name or ex.lower() in (info.get("exe") or "").lower():
            raise Blocked(f"{info.get('name')} is on the exclusion list")
    for t in store.get_list("monitor.exclude_titles"):
        if t.lower() in title:
            raise Blocked(f"window title contains '{t}' (excluded)")
    return True


def _png(width, height, bgra):
    """Encode raw top-down BGRA bytes as a PNG (RGB)."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        raw.append(0)
        raw += rgb

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def capture_window(hwnd):
    """PNG bytes of one window (works even when it is partly covered). Returns (png, width, height)."""
    winapi._need_win()
    info = winapi.window_info(hwnd)
    check_allowed(info)
    l, t, r, b = info["rect"]
    w, h = r - l, b - t
    if w <= 0 or h <= 0 or info["minimized"]:
        raise Blocked("window is minimised or has no size")
    hdc_win = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        ok = user32.PrintWindow(hwnd, mem, 2)               # PW_RENDERFULLCONTENT
        if not ok:
            gdi32.BitBlt(mem, 0, 0, w, h, hdc_win, 0, 0, 0x00CC0020)
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(bi)
        bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount, bi.biCompression = w, -h, 1, 32, 0
        buf = (ctypes.c_ubyte * (w * h * 4))()
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
        return _png(w, h, bytes(buf)), w, h
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc_win)


def save(png, app="", title="", keep=None):
    """Write a screenshot to disk (history) and prune old ones; returns the path."""
    os.makedirs(SHOTS_DIR, exist_ok=True)
    path = os.path.join(SHOTS_DIR, time.strftime("%Y%m%d-%H%M%S") + f"-{abs(hash(title)) % 10000}.png")
    with open(path, "wb") as f:
        f.write(png)
    store.x("INSERT INTO shots(ts,app,title,path,text_hash) VALUES(?,?,?,?,?)", (time.time(), app, redact(title)[:120], path, ""))
    prune()
    return path


def prune():
    limit = int(store.get("retention.shots"))
    rows = store.q("SELECT id,path FROM shots ORDER BY id DESC")
    for r in rows[limit:]:
        try:
            os.remove(r["path"])
        except OSError:
            pass
        store.x("DELETE FROM shots WHERE id=?", (r["id"],))


def pixel_hash(png):
    return hashlib.md5(png).hexdigest()


_OCR = r"""
$path=$P.path
[void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if(-not $engine){ throw 'no OCR language installed in Windows' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
$lines=@(); foreach($l in $res.Lines){ $lines+=$l.Text }
$stream.Dispose()
@{text=($lines -join "`n")}
"""


def ocr_png(png):
    """OCR on PNG bytes through Windows.Media.Ocr (local, offline). Returns redacted text."""
    from .pshost import host
    import threading, time as _t
    tmp = os.path.abspath(os.path.join(store.DATA_DIR, f"ocr_{os.getpid()}_{threading.get_ident()}_{int(_t.time() * 1000)}.png"))   # WinRT needs backslashes
    with open(tmp, "wb") as f:
        f.write(png)
    try:
        try:
            r = host.run(_OCR, {"path": tmp}, timeout=40)
        except RuntimeError:
            _t.sleep(0.5)                       # the WinRT engine occasionally fails on first use; one retry
            r = host.run(_OCR, {"path": tmp}, timeout=40)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return redact((r or {}).get("text", ""))
