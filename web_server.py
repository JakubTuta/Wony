"""
FastAPI web server shim — kept for back-compatibility.
Prefer: python wony.py web
"""
import sys

from helpers.config import Config

Config.load()

from helpers.bootstrap import BootstrapError, bootstrap

try:
    bootstrap(audio=False, seed_conversation=True)
except BootstrapError as e:
    print(f"\nCannot start: {e}\n")
    sys.exit(1)

from helpers.web_app import build_app

app = build_app()

if __name__ == "__main__":
    import uvicorn
    host = str(Config.get("server.host", "127.0.0.1"))
    port = int(Config.get("server.port", 8000))
    print(f"\nWony Web Server → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port)
