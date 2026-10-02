"""Where the local web server listens.

Always loopback: the API has no password and can run every job. The port is
picked at runtime rather than fixed — any well-known number is also held by
unrelated software — and remembered so bookmarks keep working.
"""
import socket
import typing
from urllib.parse import urlsplit

from helpers.paths import repo_path

HOST = "127.0.0.1"
LOOPBACK_NAMES = ("127.0.0.1", "localhost")

_PORT_KV_KEY = "web.port"
# Read by web/vite.config.ts so the dev server proxies to the running backend.
_RUNTIME_FILE = repo_path(".wony_server")


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def _any_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def pick_port() -> int:
    """The remembered port when it is free, otherwise a new free one (remembered)."""
    from helpers.memory_db import get_kv, set_kv

    remembered = get_kv(_PORT_KV_KEY, "")
    if remembered.isdigit() and _is_free(int(remembered)):
        port = int(remembered)
    else:
        port = _any_free_port()
        set_kv(_PORT_KV_KEY, str(port))
    try:
        with open(_RUNTIME_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(port))
    except OSError:
        pass  # only the Vite dev server reads it
    return port


def url(port: int) -> str:
    return f"http://{HOST}:{port}"


def allowed_origin(origin: typing.Optional[str], host_header: str) -> bool:
    """Whether a browser page at `origin` may talk to this server.

    Same-origin only — the page Wony itself served. The Vite dev server proxies
    `/api` and rewrites its requests' Origin to match (web/vite.config.ts), so
    it reaches this server looking same-origin too, with no separate carve-out
    needed here. A missing Origin means a non-browser client, which no website
    can drive.
    """
    if not origin:
        return True
    parts = urlsplit(origin)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK_NAMES:
        return False
    return parts.netloc == host_header
