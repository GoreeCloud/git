"""Optional, owner-authenticated, read-only web inspector. Not a Git transport."""
from __future__ import annotations

import base64
import binascii
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .core import GitError, Store, check_name
from .theme import CSS, MODES, appearance_cookie, appearance_from_cookie




def page(title: str, body: str, mode: str = "light", section: str = "repos") -> bytes:
    """Accessible GC UI shell without scripts or externally hosted assets."""
    if mode not in MODES:
        mode = "light"
    repo_current = " aria-current='page'" if section == "repos" else ""
    settings_current = " aria-current='page'" if section == "settings" else ""
    return (
        f"<!doctype html><html lang='en' data-gc-mode='{mode}'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex,nofollow'>"
        f"<title>{escape(title)} · GoreeCloud Git</title>"
        "<link rel='stylesheet' href='/assets/site.css'></head><body>"
        "<a class='skip-link' href='#main-content'>Skip to content</a>"
        "<header><div class='header-inner'><a class='brand' href='/'>GoreeCloud Git</a>"
        "<nav aria-label='Primary navigation'>"
        f"<a href='/'{repo_current}>Repositories</a>"
        f"<a href='/settings'{settings_current}>Appearance</a>"
        "</nav></div></header>"
        f"<main id='main-content'>{body}"
        "<footer class='muted'>Private owner view. Git administration and SSH transport remain separate.</footer>"
        "</main></body></html>"
    ).encode("utf-8")


def make_handler(store: Store, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "GoreeCloudGit"
        sys_version = ""

        def log_message(self, fmt: str, *args: object) -> None:
            # Do not log private repository names, URL paths, or Authorization headers.
            pass

        def headers_for(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            # Same-origin referrers remain private to this authenticated service;
            # cross-origin referrers stay suppressed. Chromium otherwise emits
            # Origin: null on the appearance POST under no-referrer, causing
            # the strict same-origin CSRF check to reject legitimate submits.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

        def respond(self, status: int, data: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.headers_for(status, content_type, len(data))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic ") or len(header) > 1024:
                return False
            try:
                credentials = base64.b64decode(header[6:], validate=True).decode("utf-8")
                username, supplied = credentials.split(":", 1)
            except (ValueError, UnicodeError, binascii.Error):
                return False
            return hmac.compare_digest(username, "owner") and hmac.compare_digest(supplied, token)

        def challenge(self, send_body: bool = True) -> None:
            data = b"Authentication required"
            self.headers_for(401, "text/plain; charset=utf-8", len(data) if send_body else 0)
            self.send_header("WWW-Authenticate", 'Basic realm="GoreeCloud Git", charset="UTF-8"')
            self.end_headers()
            if send_body:
                self.wfile.write(data)

        def appearance(self) -> str:
            return appearance_from_cookie(self.headers.get("Cookie", ""))

        def do_GET(self) -> None:
            if not self.authorized():
                self.challenge()
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            mode = self.appearance()
            if path == "/settings/appearance":
                self.headers_for(405, "text/plain; charset=utf-8", 0)
                self.send_header("Allow", "POST")
                self.end_headers()
                return
            if path == "/settings":
                labels = (("light", "Light"), ("dark", "Dark"), ("auto", "Follow system"))
                choices = "".join(
                    f"<label class='choice'><input type='radio' name='mode' value='{value}'"
                    f"{' checked' if mode == value else ''}><span>{label}</span></label>"
                    for value, label in labels
                )
                csrf = hmac.new(token.encode("ascii"), b"gcgit:appearance:v1", hashlib.sha256).hexdigest()
                body = (
                    "<section class='hero'><p class='eyebrow'>Personal settings</p>"
                    "<h1>Appearance</h1><p>Choose a comfortable reading experience. Light is the default.</p></section>"
                    "<form method='post' action='/settings/appearance' class='card'>"
                    f"<input type='hidden' name='csrf' value='{csrf}'>"
                    "<fieldset><legend>Color appearance</legend>"
                    f"<div class='choices'>{choices}</div></fieldset>"
                    "<div class='actions'><button type='submit'>Save appearance</button></div></form>"
                    "<form method='post' action='/settings/appearance' class='reset-action'>"
                    f"<input type='hidden' name='csrf' value='{csrf}'>"
                    "<button type='submit' name='mode' value='reset'>Reset to Light</button></form>"
                    "<p class='muted'>This browser stores only an appearance preference in a cookie, never Git data.</p>"
                )
                self.respond(200, page("Appearance", body, mode, "settings"))
                return
            if path == "/assets/site.css":
                self.respond(200, CSS.encode(), "text/css; charset=utf-8")
                return
            try:
                if path == "/":
                    cards = []
                    for name in store.names():
                        try:
                            info = store.info(name)
                        except (ValueError, GitError, OSError):
                            # One corrupted, unfinished or overexposed repository
                            # must not hide every healthy private repository.
                            # Only the owner sees this; never echo Git errors
                            # containing internal paths or object contents.
                            cards.append(
                                f"<article class='card'><h2>{escape(name)}</h2>"
                                "<p class='muted'>Repository unavailable. "
                                "Run <code>gcgit doctor</code> and "
                                "<code>gcgit verify</code> for inspection.</p></article>"
                            )
                            continue
                        href = quote(name)
                        cards.append(f"<article class='card'><div class='split'><h2><a href='/repos/{href}'>{escape(name)}</a></h2>"
                                     f"<span class='pill'>{info['commits']} {'commit' if info['commits'] == 1 else 'commits'}</span></div>"
                                     f"<span class='muted'>{len(info['branches'])} {'branch' if len(info['branches']) == 1 else 'branches'}</span></article>")
                    body = ("<section class='hero'><p class='eyebrow'>Your private Git workspace</p>"
                            "<h1>Private repositories</h1><p>Owner-operated source history."
                            " Only your chosen host stores repository contents.</p></section>"
                            + ("".join(cards) if cards else
                            "<div class='card'><p>No repositories yet. Create one using <code>gcgit create name</code>.</p></div>"))
                    self.respond(200, page("Repositories", body, mode, "repos"))
                    return
                if path.startswith("/repos/"):
                    name = check_name(unquote(path[len("/repos/"):]))
                    info = store.info(name)
                    items = store.recent(name)
                    history = "".join(f"<li><div class='split'><strong>{escape(row['subject'])}</strong>"
                                      f"<code>{escape(row['sha'])}</code></div>"
                                      f"<span class='muted'>{escape(row['date'])}</span></li>" for row in items)
                    branches = ", ".join(escape(x) for x in info["branches"]) or "None yet"
                    body = (f"<p><a href='/'>Repositories</a></p><h1>{escape(name)}</h1>"
                            f"<div class='card'><p><strong>Commits:</strong> {info['commits']}</p>"
                            f"<p><strong>Branches:</strong> {branches}</p></div>"
                            f"<h2>Recent history</h2><ol class='card timeline'>{history or '<li>No commits yet.</li>'}</ol>")
                    self.respond(200, page(name, body, mode, "repos"))
                    return
            except (ValueError, GitError, OSError):
                # Avoid leaking private server filesystem paths through error messages.
                self.respond(404, page("Unavailable", "<h1>Repository unavailable</h1>", mode))
                return
            self.respond(404, page("Not found", "<h1>Not found</h1>", mode))

        def do_HEAD(self) -> None:
            if not self.authorized():
                self.challenge(send_body=False)
                return
            self.headers_for(405, "text/plain; charset=utf-8", 0)
            self.send_header("Allow", "GET")
            self.end_headers()

        def do_POST(self) -> None:
            if not self.authorized():
                self.challenge()
                return
            path = urlsplit(self.path)
            if path.path != "/settings/appearance" or path.query:
                self.reject_write()
                return
            origin = self.headers.get("Origin")
            if origin:
                parsed_origin = urlsplit(origin)
                if (parsed_origin.scheme not in ("http", "https")
                        or parsed_origin.netloc != self.headers.get("Host")
                        or parsed_origin.path or parsed_origin.query or parsed_origin.fragment):
                    self.respond(403, b"Request rejected", "text/plain; charset=utf-8")
                    return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if content_type != "application/x-www-form-urlencoded" or not 1 <= length <= 512:
                self.respond(400, b"Invalid appearance", "text/plain; charset=utf-8")
                return
            try:
                data = self.rfile.read(length).decode("utf-8")
                values = parse_qs(data, keep_blank_values=True, strict_parsing=True)
            except (UnicodeError, ValueError):
                self.respond(400, b"Invalid appearance", "text/plain; charset=utf-8")
                return
            modes = values.get("mode", [])
            csrf_values = values.get("csrf", [])
            if (set(values) != {"mode", "csrf"} or len(modes) != 1
                    or modes[0] not in (*MODES, "reset") or len(csrf_values) != 1):
                self.respond(400, b"Invalid appearance", "text/plain; charset=utf-8")
                return
            expected = hmac.new(token.encode("ascii"), b"gcgit:appearance:v1", hashlib.sha256).hexdigest()
            if not hmac.compare_digest(csrf_values[0], expected):
                self.respond(403, b"Request rejected", "text/plain; charset=utf-8")
                return
            self.headers_for(303, "text/plain; charset=utf-8", 0)
            self.send_header("Set-Cookie", appearance_cookie(modes[0]))
            self.send_header("Location", "/settings")
            self.end_headers()

        def reject_write(self) -> None:
            if not self.authorized():
                self.challenge()
                return
            data = b"Method not allowed"
            self.headers_for(405, "text/plain; charset=utf-8", len(data))
            self.send_header("Allow", "GET")
            self.end_headers()
            self.wfile.write(data)

        do_PUT = reject_write
        do_DELETE = reject_write
        do_PATCH = reject_write
        do_OPTIONS = reject_write

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            # Parser/unsupported-method errors must not reveal request details
            # or silently omit response security and no-store headers.
            self.respond(code, b"Request rejected", "text/plain; charset=utf-8")

    return Handler


class LimitedWebServer(ThreadingHTTPServer):
    """Bound concurrent local HTTP connections instead of spawning unlimited threads."""

    def __init__(self, address, handler, *, max_connections: int = 8):
        if not 1 <= max_connections <= 128:
            raise ValueError("Invalid web connection limit.")
        self._slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, handler)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(10)  # slow/incomplete HTTP requests must not hold a worker forever
        return sock, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            # Overload is deliberately anonymous: no repository path or token details.
            data = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 0\r\n"
                b"Cache-Control: no-store\r\n"
                b"X-Content-Type-Options: nosniff\r\n"
                b"X-Frame-Options: DENY\r\n"
                b"Referrer-Policy: no-referrer\r\n"
                b"Connection: close\r\n\r\n"
            )
            try:
                request.sendall(data)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def serve(store: Store, host: str = "127.0.0.1", port: int = 8787) -> None:
    # The CLI also enforces loopback. Enforce here to protect direct callers.
    import ipaddress
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Web must bind to loopback only.")
    token = store.read_token()
    with LimitedWebServer((host, port), make_handler(store, token)) as server:
        print(f"Owner-only web view on http://{host}:{port} (HTTPS/SSH tunnel required remotely)")
        server.serve_forever()
