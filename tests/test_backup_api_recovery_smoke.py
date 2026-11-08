"""Pure safety checks for the opt-in GoreeCloud Backup API Git recovery drill."""
from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke-backup-api-git-recovery.py"
SPEC = importlib.util.spec_from_file_location("gcgit_backup_api_smoke", SCRIPT)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class BackupAPIRecoveryHarnessTests(unittest.TestCase):
    def test_binary_paths_must_be_absolute_executable_files(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "tool"
            file.write_text("#!/bin/sh\nexit 0\n")
            file.chmod(0o700)
            with patch.dict(os.environ, {"KOPIA_BIN": str(file)}):
                self.assertEqual(smoke.required_executable("KOPIA_BIN"), str(file))
            for value in ("", "relative-tool", td, str(Path(td) / "missing")):
                with self.subTest(value=value):
                    with patch.dict(os.environ, {"KOPIA_BIN": value}):
                        self.assertIsNone(smoke.required_executable("KOPIA_BIN"))
            file.chmod(0o600)
            with patch.dict(os.environ, {"KOPIA_BIN": str(file)}):
                self.assertIsNone(smoke.required_executable("KOPIA_BIN"))

    def test_missing_dependencies_skip_without_engine_or_service(self):
        with patch.dict(os.environ, {"KOPIA_BIN": "", "GOREECLOUD_BACKUP_BIN": ""}):
            with patch.object(sys, "argv", [str(SCRIPT)]):
                out = StringIO()
                with redirect_stderr(out):
                    self.assertEqual(smoke.main(), 77)
                self.assertIn("SKIP", out.getvalue())

    def test_encrypted_repository_copy_digest_comparison_detects_changes(self):
        with tempfile.TemporaryDirectory() as td:
            original = Path(td) / "original"
            copied = Path(td) / "copied"
            (original / "p").mkdir(parents=True)
            (copied / "p").mkdir(parents=True)
            (original / "p" / "blob").write_bytes(b"encrypted synthetic bytes")
            (copied / "p" / "blob").write_bytes(b"encrypted synthetic bytes")
            expected = smoke.encrypted_repository_digests(original)
            self.assertTrue(expected)
            self.assertEqual(expected, smoke.encrypted_repository_digests(copied))
            (copied / "p" / "blob").write_bytes(b"modified ciphertext")
            self.assertNotEqual(expected, smoke.encrypted_repository_digests(copied))

    def test_arg_injection_is_rejected(self):
        with patch.object(sys, "argv", [str(SCRIPT), "--extra"]):
            with self.assertRaises(ValueError):
                smoke.main()


if __name__ == "__main__":
    unittest.main()
