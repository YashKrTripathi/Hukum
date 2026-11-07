"""Builds gateway_bundle.zip with only the files the CRM-server gateway needs (no .env, no databases, no sessions)."""
import zipfile, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
files = ["run_gateway.py", "webserver.py", "chat_agent.py", "llm.py", "voice.py", "db.py", "config.py", "seed.py",
         "notify.py", "lc_sync.py", "hukum_mcp.py", "hermes_brain.py", "inbox.py", "pcbridge.py", "requirements-gateway.txt"]
with zipfile.ZipFile(root / "gateway_bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(root / f, f)
    for p in (root / "agents").glob("*.py"):
        z.write(p, f"agents/{p.name}")
    for p in (root / "web").glob("*"):
        if p.is_file():
            z.write(p, f"web/{p.name}")
print("wrote", root / "gateway_bundle.zip")
