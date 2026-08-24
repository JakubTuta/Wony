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
