"""Pure checks for the explicitly opt-in isolated live SSH acceptance harness."""
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke-sshd-live.py"
SPEC = importlib.util.spec_from_file_location("gcgit_live_ssh_smoke", SCRIPT)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class NamespaceLiveSmokeTests(unittest.TestCase):
    def test_mapping_uses_only_current_user_subordinate_range(self):
        user = pwd.getpwuid(os.getuid()).pw_name
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "ranges"
            f.write_text(
                f"unrelated:1000:65536\n{user}:200000:65536\n",
                encoding="ascii",
            )
            self.assertEqual(smoke.mapping_range(str(f)), (200000, 65536))
            f.write_text(f"{user}:300000:50\n", encoding="ascii")
            self.assertIsNone(smoke.mapping_range(str(f)))
            self.assertIsNone(smoke.mapping_range(str(f.parent / "missing")))

    def test_direct_inner_invocation_fails_before_any_mount(self):
        # Running as real host root must not start a disposable sshd or
        # mount anything in the host namespace.
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--inner"],
            capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic namespace UID 0", result.stderr)

    def test_fixture_requires_key_only_auth_and_no_forwarding(self):
        content = SCRIPT.read_text(encoding="utf-8")
        for setting in (
            "PasswordAuthentication no", "KbdInteractiveAuthentication no",
            "PubkeyAuthentication yes", "AllowTcpForwarding no",
            "AllowAgentForwarding no", "PermitTTY no",
            "X11Forwarding no", "PermitUserEnvironment no",
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, content)
        # Only synthetic namespace fixture disables StrictModes; this must
        # not be interpreted as a safe production sshd configuration.
        self.assertIn("StrictModes no", content)
        self.assertIn("MUST enable it", content)


if __name__ == "__main__":
    unittest.main()
