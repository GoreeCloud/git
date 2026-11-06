"""Native Git receive-pack size ceiling: disposable local repositories only."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from goreecloud_git.cli import run
from goreecloud_git.core import Store, git


def check_git(*argv):
    return subprocess.run(["git", *argv], check=True, capture_output=True, text=True)


class IncomingPackLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "private")
        self.store.init()

    def test_default_and_configurable_limits_are_persisted(self):
        default = self.store.create("default")
        custom = self.store.create("custom", max_push_mib=3)
        self.assertEqual(git("--git-dir", str(default), "config", "--get", "receive.maxInputSize"),
                         str(1024 * 1048576))
        self.assertEqual(git("--git-dir", str(custom), "config", "--get", "receive.maxInputSize"),
                         str(3 * 1048576))
        self.assertEqual(run(["--root", str(self.store.root), "create",
                              "cli-custom", "--max-push-mib", "2"]), 0)
        self.assertEqual(git("--git-dir", str(self.store.path("cli-custom")),
                             "config", "--get", "receive.maxInputSize"), str(2 * 1048576))

    def test_invalid_size_refused_before_reservation(self):
        for size in (0, -1, 16385, True, "1", 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.store.create("invalid", max_push_mib=size)
        self.assertFalse(self.store.path("invalid").exists())
        self.assertEqual(run(["--root", str(self.store.root), "create", "bad",
                              "--max-push-mib", "0"]), 1)
        self.assertFalse(self.store.path("bad").exists())

    def test_native_git_rejects_oversized_incoming_pack_without_ref_change(self):
        bare = self.store.create("limited", max_push_mib=1)
        work = self.root / "work"
        check_git("init", "-b", "main", str(work))
        (work / "README.txt").write_text("short history\n")
        check_git("-C", str(work), "add", "README.txt")
        check_git("-C", str(work), "-c", "user.name=Fixture",
                  "-c", "user.email=fixture@example.invalid",
                  "commit", "-m", "small fixture")
        remote = bare.as_uri()
        check_git("-C", str(work), "push", remote, "main")
        before = git("--git-dir", str(bare), "rev-parse", "refs/heads/main")
        (work / "large.bin").write_bytes(os.urandom(3 * 1024 * 1024))
        check_git("-C", str(work), "add", "large.bin")
        check_git("-C", str(work), "-c", "user.name=Fixture",
                  "-c", "user.email=fixture@example.invalid",
                  "commit", "-m", "large fixture")
        result = subprocess.run(["git", "-C", str(work), "push", remote, "main"],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, "Incoming pack limit unexpectedly bypassed")
        self.assertEqual(git("--git-dir", str(bare), "rev-parse", "refs/heads/main"), before)
        self.store.verify("limited")


if __name__ == "__main__":
    unittest.main()
