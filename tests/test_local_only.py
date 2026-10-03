"""Browsers do not apply CORS to WebSockets, so any website open on a machine that
can reach the server could open /api/ws, read every turn and send chat messages
— or post to the password-less API. helpers/local_only.py is the one check both
the web page and the wall panel use.

Run directly: python tests/test_local_only.py
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)


def _scope(host: str, origin: str = "", **headers: str) -> dict:
    pairs = [(b"host", host.encode())]
    if origin:
        pairs.append((b"origin", origin.encode()))
    pairs += [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return {"type": "websocket", "headers": pairs}


class TestLocalOnly(unittest.TestCase):
    def _allowed(self, scope: dict, hosts="loopback") -> bool:
        from helpers import local_only

        return local_only.allowed(scope, local_only.LOOPBACK_NAMES if hosts == "loopback" else hosts)

    def test_the_servers_own_page_is_allowed(self) -> None:
        self.assertTrue(self._allowed(_scope("localhost:8000", "http://localhost:8000")))
        self.assertTrue(self._allowed(_scope("127.0.0.1:9000", "http://127.0.0.1:9000")))

    def test_another_website_is_refused(self) -> None:
        self.assertFalse(self._allowed(_scope("localhost:8000", "https://evil.example")))
        self.assertFalse(self._allowed(_scope("localhost:8000", "http://evil.example:8000")))
        self.assertFalse(self._allowed(_scope("localhost:8000", "null")))

    def test_a_non_browser_client_sends_no_origin_and_is_allowed(self) -> None:
        self.assertTrue(self._allowed(_scope("127.0.0.1:8000")))

    def test_a_different_port_or_scheme_is_a_different_site(self) -> None:
        self.assertFalse(self._allowed(_scope("127.0.0.1:9000", "http://127.0.0.1:9001")))
        self.assertFalse(self._allowed(_scope("localhost:8000", "https://localhost:8000")))

    def test_the_dev_server_origin_is_not_special(self) -> None:
        """Vite rewrites its proxied requests' Origin to match (vite.config.ts)."""
        self.assertFalse(self._allowed(_scope("127.0.0.1:9000", "http://localhost:5173")))

    def test_a_rebound_host_name_is_refused(self) -> None:
        self.assertFalse(self._allowed(_scope("evil.example:8000", "http://evil.example:8000")))
        self.assertFalse(self._allowed(_scope("evil.example:8000")))

    def test_cross_site_fetch_metadata_is_refused_even_with_the_servers_own_origin(self) -> None:
        for site in ("cross-site", "same-site"):
            with self.subTest(site=site):
                scope = _scope("localhost:8000", "http://localhost:8000", sec_fetch_site=site)
                self.assertFalse(self._allowed(scope))

    def test_same_origin_fetch_metadata_is_allowed(self) -> None:
        scope = _scope("localhost:8000", "http://localhost:8000", sec_fetch_site="same-origin")
        self.assertTrue(self._allowed(scope))

    def test_a_screen_on_another_machine_works_when_that_host_is_served(self) -> None:
        served = ("127.0.0.1", "localhost", "192.168.1.20")
        self.assertTrue(self._allowed(_scope("192.168.1.20:8000", "http://192.168.1.20:8000"), served))
        self.assertFalse(self._allowed(_scope("192.168.1.99:8000", "http://192.168.1.99:8000"), served))

    def test_bound_to_every_interface_still_checks_the_origin(self) -> None:
        self.assertTrue(self._allowed(_scope("10.0.0.5:8000", "http://10.0.0.5:8000"), None))
        self.assertFalse(self._allowed(_scope("10.0.0.5:8000", "http://evil.example"), None))

    def test_an_ipv6_host_is_read_as_a_host_not_cut_at_a_colon(self) -> None:
        self.assertFalse(self._allowed(_scope("[::1]:8000", "http://[::1]:8000")))
        self.assertTrue(self._allowed(_scope("[::1]:8000", "http://[::1]:8000"), ("::1",)))

    def test_the_app_serves_at_least_the_loopback_names(self) -> None:
        from helpers.web_app import _allowed_hosts

        hosts = _allowed_hosts()
        self.assertTrue(hosts is None or {"127.0.0.1", "localhost"} <= set(hosts))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
