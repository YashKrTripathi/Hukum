"""MCP bridge: exposes Hukum's tools (plan, progress, exams, phone calls, memory...) to Hermes Agent.
Hermes starts this as a stdio MCP server; every call is forwarded to the local Hukum API server
(bot.py must be running). Standard library only.

Register with Hermes (see setup_hermes.md):  hermes mcp add hukum -- python D:\\learn\\placement-agents\\hukum_mcp.py
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)


def _conf():
    url = os.getenv("HUKUM_URL", "").rstrip("/")
    key = os.getenv("HUKUM_KEY", "")
    if not (url and key):
        import db
        from config import DB_PATH  # noqa: F401  (db reads the same file)
        key = key or db.get("web_key", "")
        url = url or f"http://127.0.0.1:{os.getenv('WEB_PORT', '8765')}"
    return url, key


def _call(method, path, body=None):
    url, key = _conf()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method,
                                 headers={"X-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
        return {"protocolVersion": proto, "capabilities": {"tools": {}},
                "serverInfo": {"name": "hukum", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        tools = _call("GET", "/api/tools")["tools"]
        return {"tools": [{"name": t["name"], "description": t["description"],
                           "inputSchema": t["parameters"]} for t in tools]}
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            res = _call("POST", "/api/tool", {"name": p.get("name"), "args": p.get("arguments") or {}})
            return {"content": [{"type": "text", "text": res.get("result", "")}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Hukum server error: {e}"}], "isError": True}
    return None if mid is None else {"__error__": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if "id" not in msg:        # notification (e.g. notifications/initialized): no reply
            continue
        try:
            out = handle(msg)
        except Exception as e:     # never die: Hermes would see 'Connection closed'
            out = {"__error__": {"code": -32000, "message": f"Hukum server unreachable or outdated (restart bot.py): {e}"}}
        if isinstance(out, dict) and "__error__" in out:
            _send({"jsonrpc": "2.0", "id": msg["id"], "error": out["__error__"]})
        elif out is not None:
            _send({"jsonrpc": "2.0", "id": msg["id"], "result": out})


if __name__ == "__main__":
    main()
