"""A persistent Windows PowerShell 5.1 process that runs small scripts on request. UI Automation and Windows OCR need
.NET / WinRT, and loading them once (instead of per call) makes each request fast. If a script hangs the host is
killed and restarted, so one stuck window cannot wedge the agent."""
import base64
import json
import queue
import subprocess
import threading
import time

_LOOP = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
[Console]::InputEncoding=[Text.Encoding]::UTF8
Add-Type -Namespace HK -Name Dpi -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][HK.Dpi]::SetProcessDPIAware()
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Drawing,System.Windows.Forms,System.Runtime.WindowsRuntime
$global:AsTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function global:Await($op,$type){ $t=$global:AsTask.MakeGenericMethod($type).Invoke($null,@($op)); [void]$t.Wait(-1); $t.Result }
[Console]::Out.WriteLine('@@HKREADY@@'); [Console]::Out.Flush()
while($true){
  $line=[Console]::In.ReadLine(); if($null -eq $line){break}
  try{
    $code=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line))
    $r = & ([scriptblock]::Create($code))
    $out=@{ok=$true; data=$r}
  } catch { $out=@{ok=$false; error=($_.Exception.Message)} }
  $json = $out | ConvertTo-Json -Depth 8 -Compress
  [Console]::Out.WriteLine('@@HK@@'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
  [Console]::Out.Flush()
}
"""


class PSHost:
    def __init__(self):
        self.p = None
        self.q = queue.Queue()
        self.lock = threading.Lock()

    def _start(self):
        enc = base64.b64encode(_LOOP.encode("utf-16-le")).decode()
        self.p = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, args=(self.p, self.q), daemon=True).start()
        line = self.q.get(timeout=60)
        if line != "@@HKREADY@@":
            raise RuntimeError("PowerShell host failed to start")

    @staticmethod
    def _reader(p, q):
        for raw in iter(p.stdout.readline, b""):
            q.put(raw.decode("utf-8", "replace").strip())
        q.put(None)

    def stop(self):
        if self.p and self.p.poll() is None:
            try:
                self.p.kill()
            except Exception:
                pass
        self.p = None

    def run(self, script, params=None, timeout=30):
        """Run a script block; `$P` holds `params`. Returns the script's output (parsed JSON)."""
        pre = "$P = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s')) | ConvertFrom-Json\n" % \
              base64.b64encode(json.dumps(params or {}).encode()).decode()
        payload = base64.b64encode((pre + script).encode("utf-8")).decode()
        with self.lock:
            for attempt in (0, 1):
                if not self.p or self.p.poll() is not None:
                    self._start()
                try:
                    self.p.stdin.write((payload + "\n").encode())
                    self.p.stdin.flush()
                    end = time.time() + timeout
                    while True:
                        left = end - time.time()
                        if left <= 0:
                            raise TimeoutError("PowerShell script timed out")
                        line = self.q.get(timeout=left)
                        if line is None:
                            raise OSError("PowerShell host exited")
                        if line.startswith("@@HK@@"):
                            res = json.loads(base64.b64decode(line[6:]).decode("utf-8"))
                            if not res.get("ok"):
                                raise RuntimeError(res.get("error") or "script failed")
                            return res.get("data")
                except (TimeoutError, queue.Empty):
                    self.stop()
                    raise TimeoutError("PowerShell script timed out")
                except (OSError, BrokenPipeError):
                    self.stop()
                    if attempt:
                        raise


host = PSHost()


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]
