"""Which requests the password-less local API will answer.

The API can run every job, and browsers do not apply CORS to WebSockets, so any
page open on a machine that can reach the port could otherwise drive it. The
Host check stops DNS rebinding; the Origin and Sec-Fetch-Site checks stop
cross-site requests. A missing Origin means a non-browser client, which no
website can drive.
"""
import typing
from urllib.parse import urlsplit

LOOPBACK_NAMES = ("127.0.0.1", "localhost")


def _hostname(host_header: str) -> str:
    return urlsplit("//" + host_header).hostname or ""


def allowed_origin(
    origin: typing.Optional[str],
    host_header: str,
    hosts: typing.Optional[typing.Collection[str]],
) -> bool:
    """Whether a browser page at `origin` may talk to this server.

    Same-origin only: the page Wony itself served. `hosts` is the set of host
    names that page may live at; None means any (bound to every interface, where
    the address cannot be known).
    """
    if not origin:
        return True
    parts = urlsplit(origin)
    if parts.scheme != "http":
        return False
    if hosts is not None and parts.hostname not in hosts:
        return False
    return parts.netloc == host_header


def allowed(scope: dict, hosts: typing.Optional[typing.Collection[str]]) -> bool:
    """Whether an ASGI http/websocket scope may be served."""
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
    host = headers.get("host", "")
    if hosts is not None and _hostname(host) not in hosts:
        return False
    # Belt and suspenders alongside the Origin check: a fetch() a site makes to
    # this server is neither same-origin nor absent, whatever Origin it sends.
    if headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return False
    return allowed_origin(headers.get("origin"), host, hosts)
