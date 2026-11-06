"""Optional, owner-authenticated, read-only web inspector. Not a Git transport."""
from __future__ import annotations

import base64
import binascii
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
from urllib.parse import quote, unquote, urlsplit

from .core import GitError, Store, check_name

CSS = """
:root{color-scheme:light dark;--app-canvas:#f6f7fb;--app-surface:#fff;--app-text:#192236;--app-muted:#516079;--app-border:#dae0eb;--app-accent:#5b47b0}
@media(prefers-color-scheme:dark){:root{--app-canvas:#101421;--app-surface:#1a2131;--app-text:#f2f4fc;--app-muted:#b7c2d7;--app-border:#364055;--app-accent:#b0a0ff}}
*{box-sizing:border-box}body{background:var(--app-canvas);color:var(--app-text);font:16px/1.6 system-ui,-apple-system,sans-serif;margin:0}
main{max-width:920px;margin:auto;padding:24px 20px 64px}header{border-bottom:1px solid var(--app-border);background:var(--app-surface)}
header>div{max-width:920px;margin:auto;padding:16px 20px;display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
a{color:var(--app-accent);text-underline-offset:3px}a:focus-visible{outline:3px solid var(--app-accent);outline-offset:4px;border-radius:3px}
.brand{font-weight:800;letter-spacing:.01em;color:var(--app-text);text-decoration:none}.muted{color:var(--app-muted)}
h1{font-size:clamp(1.65rem,4vw,2.45rem);line-height:1.2;margin:30px 0 10px}h2{font-size:1.12rem}
.card{background:var(--app-surface);border:1px solid var(--app-border);border-radius:14px;padding:18px 20px;margin:14px 0}
.card h2{margin:0}.split{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.pill{border:1px solid var(--app-border);color:var(--app-muted);border-radius:100px;padding:2px 12px;font-size:.82rem}
code{font: .92em ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
.timeline{list-style:none;padding:0}.timeline li{border-bottom:1px solid var(--app-border);padding:12px 0}.timeline li:last-child{border:0}
footer{margin-top:28px;color:var(--app-muted);font-size:.9rem}
@media(max-width:480px){main{padding:12px 16px 42px}.card{padding:14px}}
""".strip()


def page(title: str, body: str) -> bytes:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)} · GoreeCloud Git</title>"
            "<link rel='stylesheet' href='/assets/site.css'></head><body>"
            "<header><div><a class='brand' href='/'>GoreeCloud Git</a>"
            "<span class='pill'>Private · Read-only web</span></div></header>"
            f"<main>{body}<footer>CLI and native Git over SSH remain the authoritative write interface.</footer></main>"
            "</body></html>").encode("utf-8")


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
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")

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

        def do_GET(self) -> None:
            if not self.authorized():
                data = b"Authentication required"
                self.headers_for(401, "text/plain; charset=utf-8", len(data))
                self.send_header("WWW-Authenticate", 'Basic realm="GoreeCloud Git", charset="UTF-8"')
                self.end_headers()
                self.wfile.write(data)
                return
            path = urlsplit(self.path).path
            if path == "/assets/site.css":
                self.respond(200, CSS.encode(), "text/css; charset=utf-8")
                return
            try:
                if path == "/":
                    cards = []
                    for name in store.names():
                        info = store.info(name)
                        href = quote(name)
                        cards.append(f"<article class='card'><div class='split'><h2><a href='/repos/{href}'>{escape(name)}</a></h2>"
                                     f"<span class='pill'>{info['commits']} commits</span></div>"
                                     f"<span class='muted'>{len(info['branches'])} branches</span></article>")
                    body = ("<h1>Private repositories</h1><p class='muted'>Owner-only repository overview."
                            " Nothing here is published to GitHub.</p>" + ("".join(cards) if cards else
                            "<div class='card'><p>No repositories yet. Create one using <code>gcgit create name</code>.</p></div>"))
                    self.respond(200, page("Repositories", body))
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
                    self.respond(200, page(name, body))
                    return
            except (ValueError, GitError, OSError):
                # Avoid leaking private server filesystem paths through error messages.
                self.respond(404, page("Unavailable", "<h1>Repository unavailable</h1>"))
                return
            self.respond(404, page("Not found", "<h1>Not found</h1>"))

        def do_HEAD(self) -> None:
            self.send_error(405)

        def do_POST(self) -> None:
            self.send_error(405)

    return Handler


def serve(store: Store, host: str = "127.0.0.1", port: int = 8787) -> None:
    # The CLI also enforces loopback. Enforce here to protect direct callers.
    import ipaddress
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Web must bind to loopback only.")
    token = store.read_token()
    with ThreadingHTTPServer((host, port), make_handler(store, token)) as server:
        print(f"Owner-only web view on http://{host}:{port} (HTTPS/SSH tunnel required remotely)")
        server.serve_forever()
