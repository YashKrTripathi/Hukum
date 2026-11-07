"""Windows UI Automation (accessibility) through the PowerShell host: read what a window exposes, find controls by
name / automation id / type, invoke buttons, set text. Preferred over coordinate clicking."""
from .pshost import host, as_list

_ELEMENT = r"""
function Sint($v){ if([double]::IsInfinity($v) -or [double]::IsNaN($v)){ 0 } else { [int]$v } }
function Get-Info($e){
  try{ return (Get-Info2 $e) }catch{ return [ordered]@{ name=''; type='Unknown'; id=''; cls=''; enabled=$false; offscreen=$true; focus=$false; rect=@(0,0,0,0); patterns=@() } }
}
function Get-Info2($e){
  $c=$e.Current; $r=$c.BoundingRectangle
  $pats=@(); try{ foreach($p in $e.GetSupportedPatterns()){ $pats+=($p.ProgrammaticName -replace 'Identifiers.Pattern','') } }catch{}
  [ordered]@{ name=$c.Name; type=($c.ControlType.ProgrammaticName -replace 'ControlType.',''); id=$c.AutomationId; cls=$c.ClassName;
    enabled=$c.IsEnabled; offscreen=$c.IsOffscreen; focus=$c.HasKeyboardFocus;
    rect=@((Sint $r.Left),(Sint $r.Top),(Sint $r.Right),(Sint $r.Bottom)); patterns=$pats }
}
function Get-Root($h){ [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$h) }
function Walk($root,$maxDepth,$maxNodes,$deadline){
  $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
  $out=New-Object System.Collections.ArrayList
  $queue=New-Object System.Collections.Queue
  $queue.Enqueue(@($root,0))
  while($queue.Count -gt 0 -and $out.Count -lt $maxNodes -and ([DateTime]::Now -lt $deadline)){
    $item=$queue.Dequeue(); $el=$item[0]; $d=$item[1]
    [void]$out.Add(@{el=$el; depth=$d})
    if($d -lt $maxDepth){
      try{ $ch=$walker.GetFirstChild($el); while($ch -ne $null){ $queue.Enqueue(@($ch,($d+1))); $ch=$walker.GetNextSibling($ch) } }catch{}
    }
  }
  $out
}
function Match($el,$P){
  try{ $c=$el.Current }catch{ return $false }
  if($P.name -and ($c.Name -notlike ('*'+$P.name+'*'))){ return $false }
  if($P.exact -and ($c.Name -ne $P.exact)){ return $false }
  if($P.id -and ($c.AutomationId -ne $P.id)){ return $false }
  if($P.type -and ($c.ControlType.ProgrammaticName -ne ('ControlType.'+$P.type))){ return $false }
  $true
}
"""


def tree(hwnd, depth=4, limit=250, seconds=4):
    """Elements of a window (breadth first). Each: name,type,id,cls,enabled,offscreen,focus,rect,patterns,depth."""
    s = _ELEMENT + r"""
    $root=Get-Root $P.hwnd
    $deadline=[DateTime]::Now.AddSeconds($P.seconds)
    $res=@(); foreach($n in (Walk $root $P.depth $P.limit $deadline)){ $i=Get-Info $n.el; $i['depth']=$n.depth; $res+=,$i }
    ,$res
    """
    return as_list(host.run(s, {"hwnd": int(hwnd), "depth": depth, "limit": limit, "seconds": seconds}, timeout=seconds + 15))


def find(hwnd, name=None, exact=None, id=None, type=None, limit=20, depth=8, seconds=4):
    s = _ELEMENT + r"""
    $root=Get-Root $P.hwnd
    $deadline=[DateTime]::Now.AddSeconds($P.seconds)
    $res=@()
    foreach($n in (Walk $root $P.depth 1500 $deadline)){
      if(Match $n.el $P){ $res+=,(Get-Info $n.el); if($res.Count -ge $P.limit){break} }
    }
    ,$res
    """
    return as_list(host.run(s, {"hwnd": int(hwnd), "name": name, "exact": exact, "id": id, "type": type, "limit": limit,
                                "depth": depth, "seconds": seconds}, timeout=seconds + 15))


def invoke(hwnd, name=None, exact=None, id=None, type=None):
    """Press a control (Invoke / Toggle / SelectionItem pattern). Returns what was pressed; raises if not found."""
    s = _ELEMENT + r"""
    $root=Get-Root $P.hwnd
    $deadline=[DateTime]::Now.AddSeconds(5)
    foreach($n in (Walk $root 10 2000 $deadline)){
      if(Match $n.el $P){
        $el=$n.el; $pat=$null
        if($el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pat)){ $pat.Invoke(); return @{pressed=$el.Current.Name; via='invoke'} }
        if($el.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$pat)){ $pat.Toggle(); return @{pressed=$el.Current.Name; via='toggle'} }
        if($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pat)){ $pat.Select(); return @{pressed=$el.Current.Name; via='select'} }
        $r=$el.Current.BoundingRectangle
        return @{pressed=$el.Current.Name; via='click'; x=(Sint (($r.Left+$r.Right)/2)); y=(Sint (($r.Top+$r.Bottom)/2))}
      }
    }
    throw 'control not found'
    """
    return host.run(s, {"hwnd": int(hwnd), "name": name, "exact": exact, "id": id, "type": type}, timeout=25)


def set_value(hwnd, text, name=None, id=None, type=None):
    """Put text into an edit control through ValuePattern (no keystrokes). Returns the value read back."""
    s = _ELEMENT + r"""
    $root=Get-Root $P.hwnd
    $deadline=[DateTime]::Now.AddSeconds(5)
    foreach($n in (Walk $root 10 2000 $deadline)){
      if((Match $n.el $P) -or (-not $P.name -and -not $P.id -and -not $P.type -and $n.el.Current.ControlType.ProgrammaticName -in @('ControlType.Edit','ControlType.Document'))){
        $pat=$null
        if($n.el.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pat) -and -not $pat.Current.IsReadOnly){
          $pat.SetValue($P.text); return @{value=$pat.Current.Value}
        }
      }
    }
    throw 'no writable text control found'
    """
    return host.run(s, {"hwnd": int(hwnd), "text": text, "name": name, "id": id, "type": type}, timeout=25)


def read_text(hwnd, max_chars=20000):
    """Visible text of a window: TextPattern/ValuePattern of its text controls, else names of its labels."""
    s = _ELEMENT + r"""
    $root=Get-Root $P.hwnd
    $deadline=[DateTime]::Now.AddSeconds(5)
    $texts=New-Object System.Collections.ArrayList
    foreach($n in (Walk $root 12 1500 $deadline)){
      $el=$n.el; $t=$el.Current.ControlType.ProgrammaticName; $pat=$null
      if($el.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern,[ref]$pat)){
        try{ $x=$pat.DocumentRange.GetText($P.max); if($x){ [void]$texts.Add($x) } }catch{}
      } elseif($el.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pat)){
        $x=$pat.Current.Value; if($x -and $t -in @('ControlType.Edit','ControlType.Document')){ [void]$texts.Add($x) }
      } elseif($t -in @('ControlType.Text','ControlType.Button','ControlType.Hyperlink','ControlType.ListItem','ControlType.TabItem','ControlType.MenuItem','ControlType.Pane','ControlType.Group','ControlType.Custom','ControlType.Edit','ControlType.Document')){
        $x=$el.Current.Name; if($x -and -not $texts.Contains($x)){ [void]$texts.Add($x) }
      }
    }
    $s=($texts -join "`n"); if($s.Length -gt $P.max){ $s=$s.Substring(0,$P.max) }
    $s
    """
    r = host.run(s, {"hwnd": int(hwnd), "max": int(max_chars)}, timeout=25)
    return r or ""


def dialogs(pid=0):
    """Dialog windows (class #32770, incl. owned popups such as 'Save changes?') with their button names."""
    from . import winapi
    out = []
    for w in winapi.list_windows():
        if w["cls"] == "#32770" and (not pid or w["pid"] == pid):
            try:
                els = tree(w["hwnd"], depth=3, limit=60, seconds=2)
            except Exception:
                els = []
            buttons = [e["name"] for e in els if e.get("name") and (e.get("type") == "Button" or "button" in str(e.get("cls", "")).lower())]
            texts = [e["name"] for e in els if e.get("type") == "Text" and e.get("name")]
            out.append({"title": w["title"], "hwnd": w["hwnd"], "pid": w["pid"], "buttons": buttons, "message": " ".join(texts)[:300]})
    return out


def press(hwnd, name=None, **kw):
    """invoke(), and when the control has no Invoke pattern click its centre with the mouse (window focused first)."""
    from . import winapi, apps
    r = invoke(hwnd, name=name, **kw)
    if r.get("via") == "click":
        w = winapi.window_info(int(hwnd))
        if w:
            try:
                apps.focus(hwnd=int(hwnd))
            except Exception:
                pass
        winapi.mouse_click(int(r["x"]), int(r["y"]))
    return r
