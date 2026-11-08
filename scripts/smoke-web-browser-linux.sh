#!/bin/sh
# Opt-in, synthetic-only GC Git browser acceptance.
# No package downloads, host service installs, cloud access or production data.
set -e
if [ "$(uname -s)" != "Linux" ] || [ "$(id -u)" -eq 0 ]; then
  echo "SKIP: non-root Linux development machine required." >&2
  exit 77
fi
if [ -z "$PLAYWRIGHT_NODE_MODULES" ] || [ -z "$PLAYWRIGHT_BROWSERS" ]; then
  echo "SKIP: set verified PLAYWRIGHT_NODE_MODULES and PLAYWRIGHT_BROWSERS directories." >&2
  exit 77
fi
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="$(command -v node || true)"
fi
if [ -z "$BWRAP_BIN" ]; then
  BWRAP_BIN="$(command -v bwrap || true)"
fi
for item in "$PLAYWRIGHT_NODE_MODULES" "$PLAYWRIGHT_BROWSERS" "$NODE_BIN" "$BWRAP_BIN"; do
  case "$item" in /*) ;; *) echo "SKIP: absolute external tool paths required." >&2; exit 77;; esac
done
if [ ! -d "$PLAYWRIGHT_NODE_MODULES/playwright" ] ||
   [ ! -d "$PLAYWRIGHT_NODE_MODULES/playwright-core" ] ||
   [ ! -d "$PLAYWRIGHT_BROWSERS" ] ||
   [ ! -x "$NODE_BIN" ] || [ ! -x "$BWRAP_BIN" ]; then
  echo "SKIP: an independently inspected Playwright/Node/Bubblewrap installation is required." >&2
  exit 77
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
REPO="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
NODE_BIN="$(realpath -e "$NODE_BIN")"
PLAYWRIGHT_NODE_MODULES="$(realpath -e "$PLAYWRIGHT_NODE_MODULES")"
PLAYWRIGHT_BROWSERS="$(realpath -e "$PLAYWRIGHT_BROWSERS")"
BWRAP_BIN="$(realpath -e "$BWRAP_BIN")"
HOST_NET_NS="$(readlink /proc/self/ns/net)"
if [ -z "$HOST_NET_NS" ]; then
  echo "SKIP: current host network namespace cannot be verified." >&2
  exit 77
fi
umask 077
if [ -z "$GCGIT_BROWSER_EVIDENCE" ]; then
  GCGIT_BROWSER_EVIDENCE="$(mktemp -d /tmp/gcgit-browser-evidence-XXXXXXXX)"
fi
case "$GCGIT_BROWSER_EVIDENCE" in
  /*) ;;
  *) echo "Evidence directory must be an absolute path." >&2; exit 1 ;;
esac
if [ ! -d "$GCGIT_BROWSER_EVIDENCE" ] ||
   [ -L "$GCGIT_BROWSER_EVIDENCE" ] ||
   [ "$(stat -c %u "$GCGIT_BROWSER_EVIDENCE")" != "$(id -u)" ]; then
  echo "Evidence directory must exist and be owned by this non-root user." >&2
  exit 1
fi
if [ "$(stat -c %a "$GCGIT_BROWSER_EVIDENCE")" != "700" ]; then
  echo "Evidence directory must already be owner-private mode 0700." >&2
  exit 1
fi
echo "Disposable browser screenshots: $GCGIT_BROWSER_EVIDENCE"
exec "$BWRAP_BIN" --unshare-net \
  --clearenv --setenv HOME /tmp --setenv TMPDIR /tmp \
  --setenv PATH /usr/bin:/bin \
  --setenv NODE_PATH /opt/node_modules \
  --setenv PLAYWRIGHT_BROWSERS_PATH /opt/browsers \
  --setenv GCGIT_BROWSER_EVIDENCE /evidence \
  --setenv GCGIT_HOST_NET_NS "$HOST_NET_NS" \
  --ro-bind /usr /usr \
  --ro-bind-try /bin /bin --ro-bind-try /lib /lib --ro-bind-try /lib64 /lib64 \
  --dev /dev --proc /proc --tmpfs /tmp --tmpfs /run \
  --dir /etc --ro-bind-try /etc/fonts /etc/fonts \
  --dir /opt --ro-bind "$REPO" /opt/gcgit \
  --ro-bind "$PLAYWRIGHT_NODE_MODULES" /opt/node_modules \
  --ro-bind "$PLAYWRIGHT_BROWSERS" /opt/browsers \
  --ro-bind "$NODE_BIN" /opt/node \
  --bind "$GCGIT_BROWSER_EVIDENCE" /evidence \
  --chdir /opt/gcgit -- /opt/node /opt/gcgit/scripts/smoke-web-browser.cjs
