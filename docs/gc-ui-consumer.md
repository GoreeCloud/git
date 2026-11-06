# GoreeCloud Git — GC UI consumer alignment and acceptance

**Scope:** The optional, loopback-only read-only browser in `GoreeCloud/git`.
**Authority:** GoreeCloud UI (`GoreeCloud/gc-ui`), with the active founder-approved full design-language requirements in Google Drive `GoreeCloud/Projects/GoreeCloud UI/DESIGN-LANGUAGE-AND-100-UI-UX-PRINCIPLES.md`. This application is a consumer, not a replacement design-system authority.

## Verified implementation inputs (November 6, 2026)

The consumer maps a small set of **GC UI v1 semantic role names and exact values** from [`styles/gc.v1.generated.css`](https://github.com/GoreeCloud/gc-ui/blob/main/styles/gc.v1.generated.css) at source commit `15f479fbcf8b7f8fdde154e332b4c60f4e84385a` into [`theme.py`](../src/goreecloud_git/theme.py). It uses original local layout CSS and no third-party fonts, icons, JavaScript, build-time frameworks or external stylesheet requests. The GC UI Foundations artifact is Apache-2.0, but this project does **not** vendor or relicense that upstream source; it references the stable documented semantic values and authority. Review any subsequent design-contract changes against the same upstream source, rather than guessing palette values.

Semantic roles include `--gc-v1-color-canvas`, `--gc-v1-color-on-canvas`, `--gc-v1-color-surface`, `--gc-v1-color-on-surface`, `--gc-v1-color-on-surface-muted`, `--gc-v1-color-divider`, `--gc-v1-color-outline`, `--gc-v1-color-focus-ring`, `--gc-v1-color-link`, and corresponding approved dark-mode roles. Geometry, system typography, and 44-pixel interaction targets follow the published GC UI contract. An accessible skip link, named navigation, current-page indicator, clear card hierarchy, responsive structure, and forced-colors/reduced-motion fallbacks are present.

## Light-first appearance and user choice

- **No preference:** Light even if the operating system prefers Dark.
- **Settings > Appearance:** User can select Light, Dark, or an optional explicitly chosen Follow system mode, without JavaScript.
- **Persistence:** The owner browser stores only `gcgit_appearance` with a one-year expiry, `SameSite=Strict`, `HttpOnly`, and `Path=/`. This is a non-secret **presentation preference**, never a login token or sensitive repository metadata. It is not **synchronized** across GoreeCloud products, browsers or devices. Browser cookies are scoped to hostname and path, not TCP port; another service on the same hostname may receive this non-secret preference, so prefer separate hostnames for service isolation.
- **Reset:** Clears the preference and returns to Light. Invalid cookies and malformed parameters also resolve safely to Light (or an HTTP 400 when submitted).
- **Security:** Appearance changes and reset require an authenticated **POST** with a bounded URL-encoded form body and a constant-time validated HMAC CSRF token generated from the owner web token (not exposed as a login token). GET requests cannot change preferences. When an `Origin` header is present, a cross-origin submission is rejected. Only the non-secret appearance cookie changes; there is no Git mutation, remote Git settings API, storage publication, or filesystem write. The optional server binds to loopback, and remote administration requires a separately reviewed SSH tunnel or authenticated TLS proxy. Do not claim TLS from the local development HTTP listener.

## Evidence and remaining acceptance

The Python integration suite runs a real owner-authenticated loopback HTTP server and checks Light default, private settings access, authenticated POST+CSRF for explicit Dark/Auto selections and reset, rejection of GET changes, invalid and cross-origin POSTs, semantic GC UI token strings, focus/navigation/skip-link markup, forced-colors CSS and restrictive CSP with `form-action 'self'`. A pure-stdlib contrast regression checks the actual light and dark scheme's used text/foreground roles against their specified surfaces at **4.5:1**, and focus/outline roles against relevant surfaces at **3:1**. This checks static opaque token pairs, not rendered/composited screen contrast. The owner-authenticated repository overview now preserves healthy repository cards even when another discovered repository has broken Git refs or unsafe permissions, displaying a generic unavailable state without exposing private Git errors or filesystem paths. Native Git transport, recovery and negative security tests remain in the same CI matrix.

**Not yet complete:** actual screenshot and premium visual-composition review; authenticated remote tunnel/reverse-proxy acceptance; keyboard and screen-reader human review; phone/tablet/desktop viewport checks; browser-composited text/icon contrast and high-contrast/forced-colors behavior in supported browsers; full WCAG 2.2 AA assessment, 200–400% zoom/reflow, touch target and localization review; final founder acceptance. Source/test compliance alone does **not** certify the premium visual gate or production readiness.

## Follow-up checklist

1. Inspect the locally running authenticated UI in relevant current browsers; compare against [GC UI design language](https://github.com/GoreeCloud/gc-ui/blob/main/docs/DESIGN_LANGUAGE.md) and [component acceptance](https://github.com/GoreeCloud/gc-ui/blob/main/docs/COMPONENTS.md).
2. Exercise appearance preference on clean and returning browser profiles, Dark-preferring OS with no saved cookie, explicit Auto, reset, invalid cookie and keyboard-only navigation.
3. Record authentic screenshot and accessibility evidence before claiming a compliant consumer release. Keep the server read-only; do not add remote write APIs or frontend scripts merely to satisfy appearance settings.
