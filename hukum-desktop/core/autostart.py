"""Start with Windows (HKCU Run key, no admin needed) and the system-tray icon (separate hidden PowerShell process that
talks to the local dashboard server with the access token; it exits when Hukum exits)."""
import base64
import os
import subprocess
import sys

NAME = "HukumDesktop"
KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tray = {"proc": None}


def _command():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" "{os.path.join(ROOT, "hukum_desktop.py")}" --no-browser'


def is_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            return bool(winreg.QueryValueEx(k, NAME)[0])
    except OSError:
        return False


def set_enabled(on):
    if sys.platform != "win32":
        raise RuntimeError("autostart is Windows-only")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(k, NAME)
            except FileNotFoundError:
                pass
    return is_enabled()


_PS = r"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$port=$env:HK_PORT; $tok=$env:HK_TOKEN; $ppid=[int]$env:HK_PPID
$base="http://127.0.0.1:$port"
function Call($path,$body){ try{ Invoke-RestMethod -Uri "$base$path" -Method Post -Headers @{'X-Token'=$tok} -ContentType 'application/json' -Body $body -TimeoutSec 5 | Out-Null }catch{} }
$n=New-Object System.Windows.Forms.NotifyIcon
$n.Icon=[System.Drawing.SystemIcons]::Shield; $n.Text='Hukum'; $n.Visible=$true
$m=New-Object System.Windows.Forms.ContextMenuStrip
$open={ Start-Process "$base/?t=$tok" }
[void]$m.Items.Add('Open dashboard',$null,$open)
[void]$m.Items.Add('EMERGENCY STOP',$null,{ Call '/api/estop' '{"on":true}'; $n.ShowBalloonTip(3000,'Hukum','Emergency stop is ON','Warning') })
[void]$m.Items.Add('Release emergency stop',$null,{ Call '/api/estop' '{"on":false}' })
[void]$m.Items.Add('Quit Hukum',$null,{ Call '/api/quit' '{}'; $n.Visible=$false; [System.Windows.Forms.Application]::Exit() })
$n.ContextMenuStrip=$m; $n.add_DoubleClick($open)
$t=New-Object System.Windows.Forms.Timer; $t.Interval=3000
$t.add_Tick({ if(-not (Get-Process -Id $ppid -ErrorAction SilentlyContinue)){ $n.Visible=$false; [System.Windows.Forms.Application]::Exit() } })
$t.Start()
[System.Windows.Forms.Application]::Run()
$n.Dispose()
"""


def start_tray(port, token):
    if sys.platform != "win32" or (_tray["proc"] and _tray["proc"].poll() is None):
        return False
    env = dict(os.environ, HK_PORT=str(port), HK_TOKEN=token, HK_PPID=str(os.getpid()))
    _tray["proc"] = subprocess.Popen(["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-EncodedCommand",
                                      base64.b64encode(_PS.encode("utf-16-le")).decode()], env=env, creationflags=0x08000000,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def stop_tray():
    p = _tray["proc"]
    if p and p.poll() is None:
        p.terminate()
    _tray["proc"] = None
