"""Centralized HTTP client with baked-in timeouts.

Modules must call get/post/put/delete/request from here instead of `requests`
directly. A bare `requests.get(...)` with no timeout blocks forever if the
target hangs.

(connect, read) timeouts, not a total-duration timeout — a slow-but-alive
server keeps going as long as each individual read arrives within
_READ_TIMEOUT. Override per-call with timeout=... if a specific endpoint
needs something different.
"""

import typing

import requests

_CONNECT_TIMEOUT = 3.0
_READ_TIMEOUT = 8.0
_DEFAULT_TIMEOUT = (_CONNECT_TIMEOUT, _READ_TIMEOUT)


def is_public_url(url: str) -> bool:
    """True when `url` is http(s) and every address its host resolves to is on
    the public internet.

    Pages and emails can carry links, and the model follows them. Without this
    a link could reach Wony's own password-less API, the router's admin page or
    Home Assistant on the local network.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa")):
        return False
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            return False
    return bool(infos)


def request(method: str, url: str, **kwargs: typing.Any) -> requests.Response:
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    return requests.request(method, url, **kwargs)


def get(url: str, **kwargs: typing.Any) -> requests.Response:
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    return requests.get(url, **kwargs)


def post(url: str, **kwargs: typing.Any) -> requests.Response:
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    return requests.post(url, **kwargs)


def put(url: str, **kwargs: typing.Any) -> requests.Response:
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    return requests.put(url, **kwargs)


def delete(url: str, **kwargs: typing.Any) -> requests.Response:
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    return requests.delete(url, **kwargs)
