"""The web UI is authenticated, read-only, and escapes untrusted Git metadata."""
import base64
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from goreecloud_git.core import Store
from goreecloud_git.web import make_handler


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "private")
        self.store.init()
        self.store.create("example")
        self.token = self.store.rotate_token()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, self.token))
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


if __name__ == "__main__":
    unittest.main()
