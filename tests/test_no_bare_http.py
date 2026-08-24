"""Guards against reintroducing unbounded HTTP calls in modules/.

A bare requests.get/post() has no timeout and can hang a whole voice turn (see
logs/ai_assistant_20260801_122648.log — a Shelly call with no timeout blocked a
turn for 1m45s). modules/ must call helpers.net instead, which bakes a
(connect, read) timeout in.

httpx is covered too: it is a second HTTP client that bypasses helpers.net
entirely, so the original requests-only guard did not see modules/web.py.
Run directly: python tests/test_no_bare_http.py
"""
import glob
import os
import re
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULES_DIR = os.path.join(_REPO_ROOT, "modules")

_VERBS = "get|post|put|delete|patch|request|head|options"
_BARE_REQUESTS = re.compile(rf"\brequests\.({_VERBS})\s*\(")
# httpx.get(...) / httpx.post(...) — a bare module-level call with no client.
_BARE_HTTPX = re.compile(rf"\bhttpx\.({_VERBS})\s*\(")
# ...unless the very same call passes an explicit timeout.
_HAS_TIMEOUT = re.compile(r"\btimeout\s*=")


def _offenders(pattern: re.Pattern) -> list:
    found = []
    for path in sorted(glob.glob(os.path.join(_MODULES_DIR, "*.py"))):
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        for match in pattern.finditer(source):
            # Look at the whole call expression, which may span lines.
            tail = source[match.end() : match.end() + 400]
            depth = 1
            end = 0
            for i, ch in enumerate(tail):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            call_args = tail[:end]
            if _HAS_TIMEOUT.search(call_args):
                continue
            lineno = source[: match.start()].count("\n") + 1
            rel = os.path.relpath(path, _REPO_ROOT)
            found.append(f"{rel}:{lineno}: {match.group(0)}...)")
    return found


class TestNoBareHttp(unittest.TestCase):
    def test_modules_use_helpers_net(self) -> None:
        self.assertFalse(
            _offenders(_BARE_REQUESTS),
            "Bare requests.* calls found — route through helpers.net instead:\n"
            + "\n".join(_offenders(_BARE_REQUESTS)),
        )

    def test_httpx_calls_pass_a_timeout(self) -> None:
        self.assertFalse(
            _offenders(_BARE_HTTPX),
            "httpx call without an explicit timeout — a hung endpoint blocks the "
            "whole turn:\n" + "\n".join(_offenders(_BARE_HTTPX)),
        )


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
