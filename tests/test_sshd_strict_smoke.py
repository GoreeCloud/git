"""Pure safety preflight for opt-in synthetic non-root StrictModes smoke."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke-sshd-strict.py"
SPEC = importlib.util.spec_from_file_location("gcgit_strict_smoke", SCRIPT)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class SyntheticStrictModesTests(unittest.TestCase):
    def test_subordinate_ranges_are_required_and_owned(self):
        user = pwd.getpwuid(smoke.os.getuid()).pw_name
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "subuids"
            config.write_text("other:100000:65536\n"
                              + f"{user}:500000:65536\n")
            self.assertEqual(smoke.assigned_range(str(config)), (500000, 65536))
            config.write_text(f"{user}:500000:1001\n")
            self.assertIsNone(smoke.assigned_range(str(config)))
            config.write_text(f"{user}:500000:65534\n")
            self.assertIsNone(smoke.assigned_range(str(config)))
            self.assertIsNone(smoke.assigned_range(str(config.parent / "missing")))

    def test_direct_inner_outer_invocation_fails_closed_without_namespace(self):
        # Neither entrypoint may mount/modify the real host's /run, /dev, /etc
        # or launch sshd in the host network namespace.
        for mode in ("--inner", "--outer"):
            with self.subTest(mode=mode):
                r = subprocess.run([sys.executable, str(SCRIPT), mode],
                                   capture_output=True, text=True, timeout=5)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("Refusing to run", r.stderr)

    def test_synthetic_account_and_secure_sshd_policy_are_explicit(self):
        src = SCRIPT.read_text()
        for expected in (
            "gcgit:x:1001:1001", "StrictModes yes", "PermitRootLogin no",
            "AllowUsers gcgit", "PasswordAuthentication no",
            "KbdInteractiveAuthentication no", "AllowTcpForwarding no",
            "AllowAgentForwarding no", "PermitUserEnvironment no",
            "X11Forwarding no", "PermitTTY no",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, src)
        self.assertNotIn("StrictModes no", src)
        self.assertIn("unshare", src)
        self.assertIn("chroot", src)


if __name__ == "__main__":
    unittest.main()
