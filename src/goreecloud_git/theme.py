"""GC UI v1 semantic appearance values for the self-contained, no-JavaScript web view.

The small selection of token values below is checked against GoreeCloud/gc-ui
styles/gc.v1.generated.css at main 15f479fbcf8b7f8fdde154e332b4c60f4e84385a.
The authority is GC UI; this module is a consumer mapping, not a second design system.
"""
from http.cookies import CookieError, SimpleCookie

COOKIE_NAME = "gcgit_appearance"
MODES = ("light", "dark", "auto")


def appearance_from_cookie(raw: str) -> str:
    """Default to Light, independent of operating-system color preference."""
    if not isinstance(raw, str) or len(raw) > 4096 or "\r" in raw or "\n" in raw:
        return "light"
    jar = SimpleCookie()
    try:
        jar.load(raw)
        cookie = jar.get(COOKIE_NAME)
        value = cookie.value if cookie is not None else None
    except (CookieError, ValueError):
        return "light"
    return value if value in MODES else "light"


def appearance_cookie(mode: str) -> str:
    """Only non-sensitive appearance is retained, never login or Git credentials."""
    if mode == "reset":
        return f"{COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Strict; HttpOnly"
    if mode not in MODES:
        raise ValueError("Invalid appearance")
    return f"{COOKIE_NAME}={mode}; Path=/; Max-Age=31536000; SameSite=Strict; HttpOnly"


CSS = """
/* GC UI v1 semantic roles (light-first), sourced from GoreeCloud/gc-ui.
   Compact owner-browser consumer mapping; no third-party fonts or scripts. */
:root {
  color-scheme:light;
  --gc-v1-color-canvas:#ECF0F8; --gc-v1-color-on-canvas:#20243A;
  --gc-v1-color-surface:#F9FAFD; --gc-v1-color-on-surface:#20243A;
  --gc-v1-color-surface-raised:#FFFFFF; --gc-v1-color-surface-tonal:#E5EBF6;
  --gc-v1-color-on-surface-muted:#5F657B; --gc-v1-color-divider:#E5E7F0;
  --gc-v1-color-outline:#8990A7; --gc-v1-color-focus-ring:#4132B3;
  --gc-v1-color-link:#4034B9; --gc-v1-color-secondary-container:#E2E8FA;
  --gc-v1-color-on-secondary-container:#28395D;
  --gc-v1-foundation-radius-sm:12px; --gc-v1-foundation-radius-md:18px;
  --gc-v1-foundation-radius-lg:26px; --gc-v1-foundation-radius-pill:999px;
  --gc-v1-foundation-typography-family-ui:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --gc-v1-foundation-typography-family-mono:ui-monospace,Consolas,monospace;
}
:root[data-gc-mode="dark"] {
  color-scheme:dark;
  --gc-v1-color-canvas:#10131E; --gc-v1-color-on-canvas:#F2F2FA;
  --gc-v1-color-surface:#1D2231; --gc-v1-color-on-surface:#F2F2FA;
  --gc-v1-color-surface-raised:#252B3D; --gc-v1-color-surface-tonal:#292F40;
  --gc-v1-color-on-surface-muted:#B3B9CF; --gc-v1-color-divider:#373C50;
  --gc-v1-color-outline:#747C99; --gc-v1-color-focus-ring:#D8D2FF;
  --gc-v1-color-link:#C5BFFF; --gc-v1-color-secondary-container:#374969;
  --gc-v1-color-on-secondary-container:#E8ECFF;
}
@media (prefers-color-scheme:dark) {
  :root[data-gc-mode="auto"] {
    color-scheme:dark;
    --gc-v1-color-canvas:#10131E; --gc-v1-color-on-canvas:#F2F2FA;
    --gc-v1-color-surface:#1D2231; --gc-v1-color-on-surface:#F2F2FA;
    --gc-v1-color-surface-raised:#252B3D; --gc-v1-color-surface-tonal:#292F40;
    --gc-v1-color-on-surface-muted:#B3B9CF; --gc-v1-color-divider:#373C50;
    --gc-v1-color-outline:#747C99; --gc-v1-color-focus-ring:#D8D2FF;
    --gc-v1-color-link:#C5BFFF; --gc-v1-color-secondary-container:#374969;
    --gc-v1-color-on-secondary-container:#E8ECFF;
  }
}
@media (forced-colors:active) {
  :root {
    --gc-v1-color-canvas:Canvas !important;
    --gc-v1-color-on-canvas:CanvasText !important;
    --gc-v1-color-surface:Canvas !important;
    --gc-v1-color-on-surface:CanvasText !important;
    --gc-v1-color-surface-raised:Canvas !important;
    --gc-v1-color-surface-tonal:Canvas !important;
    --gc-v1-color-on-surface-muted:CanvasText !important;
    --gc-v1-color-divider:ButtonText !important;
    --gc-v1-color-outline:ButtonText !important;
    --gc-v1-color-focus-ring:Highlight !important;
    --gc-v1-color-link:LinkText !important;
    --gc-v1-color-secondary-container:Canvas !important;
    --gc-v1-color-on-secondary-container:CanvasText !important;
  }
}
*,*::before,*::after {box-sizing:border-box}
html {scroll-behavior:smooth}
body {margin:0;min-width:0;background:var(--gc-v1-color-canvas);color:var(--gc-v1-color-on-canvas);
  font:1rem/1.55 var(--gc-v1-foundation-typography-family-ui)}
a {color:var(--gc-v1-color-link);text-underline-offset:3px}
a:hover {text-decoration-thickness:2px}
a:focus-visible,button:focus-visible,input:focus-visible {
  outline:3px solid var(--gc-v1-color-focus-ring);outline-offset:3px}
.skip-link {position:absolute;left:16px;top:-100px;z-index:10;padding:12px 16px;
  background:var(--gc-v1-color-surface);color:var(--gc-v1-color-on-surface)}
.skip-link:focus {top:10px}
header {background:var(--gc-v1-color-surface);border-bottom:1px solid var(--gc-v1-color-divider)}
.header-inner {max-width:980px;margin:auto;padding:18px 22px;display:flex;gap:18px;align-items:center;
  justify-content:space-between;flex-wrap:wrap}
.brand {font-weight:750;letter-spacing:-.02em;color:var(--gc-v1-color-on-surface);text-decoration:none;font-size:19px}
nav {display:flex;gap:8px;flex-wrap:wrap;align-items:center}
nav a {display:inline-flex;min-height:44px;align-items:center;padding:8px 14px;border-radius:var(--gc-v1-foundation-radius-sm);
  color:var(--gc-v1-color-on-surface);text-decoration:none}
nav a[aria-current="page"] {background:var(--gc-v1-color-surface-tonal);font-weight:680}
nav a:hover {background:var(--gc-v1-color-surface-tonal)}
main {max-width:980px;margin:auto;padding:24px 22px 60px}
.hero {padding:26px clamp(18px,4vw,36px);background:var(--gc-v1-color-secondary-container);
  color:var(--gc-v1-color-on-secondary-container);border-radius:var(--gc-v1-foundation-radius-lg);
  border:1px solid var(--gc-v1-color-divider);margin-bottom:30px}
.eyebrow {font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px}
h1 {font-size:clamp(1.8rem,4.5vw,2.55rem);letter-spacing:-.035em;line-height:1.2;margin:0 0 10px}
h2 {font-size:1.12rem;line-height:1.4;margin:0 0 4px}
p {margin:0 0 12px} .hero p {max-width:60ch;margin-bottom:0}
.muted {color:var(--gc-v1-color-on-surface-muted)}
.card {background:var(--gc-v1-color-surface);border:1px solid var(--gc-v1-color-divider);
  border-radius:var(--gc-v1-foundation-radius-md);padding:20px 24px;margin:12px 0}
.card h2 {margin:0}
.split {display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px}
.pill {display:inline-flex;align-items:center;min-height:30px;border:1px solid var(--gc-v1-color-outline);
  padding:2px 12px;border-radius:var(--gc-v1-foundation-radius-pill);font-size:.81rem}
code {font:.9em/1.6 var(--gc-v1-foundation-typography-family-mono);overflow-wrap:anywhere}
.timeline {list-style:none;padding:0} .timeline li {padding:14px 0;border-bottom:1px solid var(--gc-v1-color-divider)}
.timeline li:last-child {border-bottom:0}
fieldset {border:0;padding:0;margin:0}legend {font-size:1.2rem;font-weight:680;margin-bottom:12px}
.choices {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:12px}
.choice {display:flex;gap:10px;align-items:center;min-height:50px;padding:12px 16px;
  background:var(--gc-v1-color-surface-tonal);border-radius:var(--gc-v1-foundation-radius-sm);
  border:1px solid var(--gc-v1-color-outline);cursor:pointer}
.choice input {width:18px;height:18px;accent-color:var(--gc-v1-color-link)}
.actions {display:flex;gap:12px;flex-wrap:wrap;margin-top:22px;align-items:center}
button {min-height:44px;padding:10px 22px;border:1px solid var(--gc-v1-color-outline);
  border-radius:var(--gc-v1-foundation-radius-sm);background:var(--gc-v1-color-surface-tonal);
  color:var(--gc-v1-color-on-surface);font:inherit;font-weight:650;cursor:pointer}
button:hover {background:var(--gc-v1-color-secondary-container);color:var(--gc-v1-color-on-secondary-container)}
footer {margin-top:36px;padding-top:16px;border-top:1px solid var(--gc-v1-color-divider);font-size:.875rem}
@media (max-width:480px) {
  main {padding:16px 14px 42px}
  .header-inner {padding:12px 14px}
  .card {padding:16px}
  nav {width:100%;justify-content:space-between}
}
@media (prefers-reduced-motion:reduce) {html {scroll-behavior:auto}}
""".strip()
