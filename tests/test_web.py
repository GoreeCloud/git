"""The web UI is authenticated, read-only, and escapes untrusted Git metadata."""
import base64
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest

from goreecloud_git.core import Store
from goreecloud_git.web import LimitedWebServer, make_handler


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "private")
        self.store.init()
        self.store.create("example")
        self.token = self.store.rotate_token()
        self.server = LimitedWebServer(("127.0.0.1", 0), make_handler(self.store, self.token), max_connections=2)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path="/", method="GET", auth=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {}
        if auth is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(("owner:" + auth).encode()).decode()
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode()
        result = (response.status, body, dict(response.getheaders()))
        connection.close()
        return result

    def test_authentication_required_for_all_resources(self):
        for path in ("/", "/repos/example", "/assets/site.css"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request(auth="bad")[0], 401)
        self.assertEqual(self.request(auth=self.token)[0], 200)

    def test_repository_overview_and_detail(self):
        status, body, headers = self.request(auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("example", body)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        status, body, _ = self.request("/repos/example", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("No commits yet", body)
        self.assertNotIn(str(self.store.root), body)

    def test_path_traversal_and_write_rejected(self):
        self.assertEqual(self.request("/repos/%2E%2E%2Foutside", auth=self.token)[0], 404)
        self.assertEqual(self.request("/does-not-exist", auth=self.token)[0], 404)
        self.assertEqual(self.request("/", method="POST", auth=self.token)[0], 405)

    def test_overload_returns_anonymous_503_and_recovers(self):
        self.assertTrue(self.server._slots.acquire(blocking=False))
        self.assertTrue(self.server._slots.acquire(blocking=False))
        try:
            status, body, headers = self.request("/repos/example", auth=self.token)
            self.assertEqual(status, 503)
            self.assertEqual(body, "")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn(str(self.store.root), str(headers))
        finally:
            self.server._slots.release()
            self.server._slots.release()
        self.assertEqual(self.request(auth=self.token)[0], 200)

    def test_invalid_web_connection_limits_rejected(self):
        for limit in (0, -1, 129):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                LimitedWebServer(("127.0.0.1", 0), make_handler(self.store, self.token),
                                 max_connections=limit)

    def test_disallowed_http_methods_require_auth_and_no_store(self):
        for method in ("HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            with self.subTest(method=method):
                status, _, headers = self.request("/", method=method)
                self.assertEqual(status, 401)
                self.assertIn("no-store", headers["Cache-Control"])
                status, _, headers = self.request("/", method=method, auth=self.token)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET")
                self.assertIn("no-store", headers["Cache-Control"])
                self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        status, _, headers = self.request("/", method="BREW", auth=self.token)
        self.assertEqual(status, 501)
        self.assertIn("no-store", headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
