"""The web UI is authenticated, read-only, and escapes untrusted Git metadata."""
import base64
import re
from http.client import HTTPConnection
from urllib.parse import urlencode
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

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

    def request(self, path="/", method="GET", auth=None, cookie=None,
                body=None, origin=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {}
        if cookie is not None:
            headers["Cookie"] = cookie
        if auth is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(("owner:" + auth).encode()).decode()
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if origin is not None:
            headers["Origin"] = origin
        connection.request(method, path, body=body, headers=headers)
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

    def test_gc_ui_semantics_and_light_first(self):
        status, body, headers = self.request("/", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("data-gc-mode='light'", body)
        self.assertIn("Skip to content", body)
        self.assertIn("aria-current='page'", body)
        self.assertIn("<nav aria-label='Primary navigation'>", body)
        self.assertNotIn("<script", body)
        self.assertIn("form-action 'self'", headers["Content-Security-Policy"])
        # Same-origin allows real browser form Origin headers, yet suppresses
        # outgoing cross-site Referer details (private repo names/paths).
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        status, css, _ = self.request("/assets/site.css", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("--gc-v1-color-canvas:#ECF0F8", css)
        self.assertIn("--gc-v1-color-canvas:#10131E", css)
        self.assertIn(':root[data-gc-mode="dark"]', css)
        self.assertIn(':root[data-gc-mode="auto"]', css)
        self.assertIn("forced-colors:active", css)
        self.assertNotIn("--app-canvas:", css)

    def csrf_value(self):
        status, body, _ = self.request("/settings", auth=self.token)
        self.assertEqual(status, 200)
        match = re.search(r"name='csrf' value='([a-f0-9]{64})'", body)
        self.assertIsNotNone(match)
        return match.group(1)

    def post_appearance(self, mode, *, csrf=None, auth="owner", origin=None):
        form = urlencode({"mode": mode, "csrf": self.csrf_value() if csrf is None else csrf})
        credentials = self.token if auth == "owner" else auth
        return self.request("/settings/appearance", method="POST",
                            auth=credentials, body=form, origin=origin)

    def test_appearance_is_private_persistent_and_resettable(self):
        self.assertEqual(self.request("/settings")[0], 401)
        status, body, _ = self.request("/settings", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("data-gc-mode='light'", body)
        self.assertIn("name='mode' value='light' checked", body)
        self.assertIn("method='post' action='/settings/appearance'", body)
        self.assertIn("Follow system", body)
        status, _, headers = self.request("/settings/appearance?mode=dark", auth=self.token)
        self.assertEqual(status, 405)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(self.post_appearance("dark", auth=None)[0], 401)
        status, _, headers = self.post_appearance("dark")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/settings")
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, body, _ = self.request("/settings", auth=self.token, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("data-gc-mode='dark'", body)
        self.assertIn("name='mode' value='dark' checked", body)
        self.assertEqual(self.request("/", auth=self.token, cookie=cookie)[0], 200)
        status, _, headers = self.post_appearance("auto")
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("data-gc-mode='auto'",
                      self.request("/settings", auth=self.token, cookie=cookie)[1])
        status, _, headers = self.post_appearance("reset")
        self.assertEqual(status, 303)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIn("data-gc-mode='light'", self.request("/", auth=self.token)[1])

    def test_invalid_appearance_parameters_fail_closed(self):
        valid_csrf = self.csrf_value()
        for body in (
            "", "mode=", "mode=evil", "mode=dark&mode=light",
            "mode=dark&extra=yes", "other=dark", "mode=%0D%0Aattack",
            "mode=dark", f"mode=dark&csrf={valid_csrf}&csrf={valid_csrf}",
            f"mode=dark&csrf={valid_csrf}&extra=yes",
            "x" * 520,
        ):
            with self.subTest(body=body[:60]):
                status, _, headers = self.request(
                    "/settings/appearance", method="POST", auth=self.token, body=body
                )
                self.assertIn(status, (400, 403))
                self.assertNotIn("Set-Cookie", headers)
                self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(self.post_appearance("dark", csrf="0" * 64)[0], 403)
        self.assertEqual(self.post_appearance("dark", origin="https://evil.example")[0], 403)
        self.assertEqual(self.post_appearance("dark", origin="null")[0], 403)
        allowed_origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.post_appearance("dark", origin=allowed_origin)[0], 303)
        status, body, _ = self.request("/", auth=self.token, cookie="gcgit_appearance=malicious")
        self.assertEqual(status, 200)
        self.assertIn("data-gc-mode='light'", body)

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

    def test_overview_uses_singular_labels_for_one_commit_and_branch(self):
        with patch.object(self.store, "info",
                          return_value={"name": "example", "commits": 1, "branches": ["main"]}):
            status, body, _ = self.request("/", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("1 commit", body)
        self.assertIn("1 branch", body)
        self.assertNotIn("1 commits", body)
        self.assertNotIn("1 branches", body)

    def test_overview_survives_private_repository_permission_failure(self):
        unsafe = self.store.create("unsafe")
        unsafe.chmod(0o755)
        status, body, headers = self.request("/", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("example", body)
        self.assertIn("unsafe", body)
        self.assertIn("Repository unavailable", body)
        self.assertIn("gcgit doctor", body)
        self.assertNotIn(str(self.store.root), body)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(self.request("/repos/unsafe", auth=self.token)[0], 404)
        self.assertEqual(self.request("/", auth=None)[0], 401)

    def test_overview_survives_corrupt_git_refs(self):
        corrupt = self.store.create("corrupt")
        (corrupt / "refs/heads/main").write_text("not-a-valid-object-id")
        status, body, _ = self.request("/", auth=self.token)
        self.assertEqual(status, 200)
        self.assertIn("<a href='/repos/example'>example</a>", body)
        self.assertIn("corrupt", body)
        self.assertIn("Repository unavailable", body)
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
