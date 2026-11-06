"""Pure preflight checks for optional encrypted Kopia/Git restore smoke."""
from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
from io import StringIO
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke-kopia-git-recovery.py"
SPEC = importlib.util.spec_from_file_location("gcgit_kopia_smoke", SCRIPT)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class EncryptedRestoreHarnessTests(unittest.TestCase):
    def test_restore_destination_reservation_is_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            destination = root / "restore"
            smoke.reserve_empty_restore(destination)
            self.assertTrue(destination.is_dir())
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            with self.assertRaises(ValueError):
                smoke.reserve_empty_restore(destination)

            sentinel = destination / "preserve.txt"
            sentinel.write_text("original")
            with self.assertRaises(ValueError):
                smoke.reserve_empty_restore(destination)
            self.assertEqual(sentinel.read_text(), "original")

    def test_symlinked_restore_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "absent"
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                smoke.reserve_empty_restore(alias)
            self.assertFalse(target.exists())
            self.assertTrue(alias.is_symlink())

    def test_unavailable_kopia_skips_without_backup_or_install(self):
        with patch.dict(os.environ, {"KOPIA_BIN": "", "PATH": "/nonexistent"}):
            with patch.object(sys, "argv", [str(SCRIPT)]):
                output = StringIO()
                with redirect_stderr(output):
                    self.assertEqual(smoke.main(), 77)
            self.assertIn("SKIP: external Kopia CLI", output.getvalue())


if __name__ == "__main__":
    unittest.main()
