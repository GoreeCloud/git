"""Integration tests use real Git but isolated temporary private directories."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from goreecloud_git.cli import run
from goreecloud_git.core import GitError, Store, check_name


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "private")
        self.store.init()

    def test_init_modes(self):
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.repos.stat().st_mode), 0o700)

    def test_repository_create_list_and_ref_safety(self):
        bare = self.store.create("my-project")
        self.assertEqual(stat.S_IMODE(bare.stat().st_mode), 0o700)
        self.assertEqual(self.store.names(), ["my-project"])
        self.assertEqual(self.store.info("my-project")["commits"], 0)
        self.assertEqual(self.store.recent("my-project"), [])
        with self.assertRaises(GitError):
            self.store.create("my-project")
        self.assertEqual(subprocess.check_output(
            ["git", "--git-dir", str(bare), "config", "--get", "receive.denyDeletes"], text=True).strip(), "true")

    def test_invalid_names_and_traversal(self):
        for name in ("", "..", ".", "x/y", "../bad", "name.git", "a." , "a b", "a\n", "a"*64, "-bad"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_name(name)
        self.assertEqual(check_name("alpha_9.test"), "alpha_9.test")
        self.assertEqual(self.store.names(), [])

    def test_symlink_repo_not_followed(self):
        target = Path(self.tmp.name) / "elsewhere.git"
        target.mkdir()
        (self.store.repos / "shadow.git").symlink_to(target, target_is_directory=True)
        self.assertEqual(self.store.names(), [])
        with self.assertRaises(GitError):
            self.store.existing("shadow")

    def test_must_not_repair_insecure_existing_root(self):
        os.chmod(self.store.root, 0o755)
        with self.assertRaises(GitError):
            self.store.init()
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o755)

    def test_remote_url(self):
        self.store.create("alpha")
        self.assertEqual(self.store.ssh_url("alpha", "git.example.test", "gcgit", 2222),
                         f"ssh://gcgit@git.example.test:2222{self.store.path('alpha')}")
        with self.assertRaises(ValueError):
            self.store.ssh_url("alpha", "example.com/../bad")

    def test_native_git_push_and_clone(self):
        bare = self.store.create("native")
        working = Path(self.tmp.name) / "working"
        cloned = Path(self.tmp.name) / "cloned"
        subprocess.run(["git", "init", "-b", "main", str(working)], check=True, capture_output=True)
        (working / "note.txt").write_text("private Git data\n")
        subprocess.run(["git", "-C", str(working), "add", "note.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Private test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "remote", "add", "origin", str(bare)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "push", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(bare), str(cloned)], check=True, capture_output=True)
        self.assertEqual((cloned / "note.txt").read_text(), "private Git data\n")
        self.assertEqual(self.store.info("native")["commits"], 1)
        self.assertEqual(len(self.store.recent("native")), 1)
        self.assertEqual(self.store.recent("native")[0]["subject"], "Private test")

    def test_integrity_check_empty_and_missing(self):
        self.store.create("integrity")
        self.store.verify("integrity")
        with self.assertRaises(GitError):
            self.store.verify("missing")

    def test_integrity_check_detects_corrupt_ref(self):
        bare = self.store.create("corrupt")
        (bare / "refs/heads/main").write_text("not-a-valid-object-id\n")
        with self.assertRaises(GitError):
            self.store.verify("corrupt")

    def test_doctor_refuses_insecure_web_token(self):
        self.store.rotate_token()
        self.assertEqual(run(["--root", str(self.store.root), "doctor"]), 0)
        os.chmod(self.store.token_path(), 0o644)
        self.assertEqual(run(["--root", str(self.store.root), "doctor"]), 1)

    def test_cli_verify(self):
        self.store.create("project")
        self.assertEqual(run(["--root", str(self.store.root), "verify", "project"]), 0)

    def test_token_lifecycle(self):
        a = self.store.rotate_token()
        self.assertEqual(a, self.store.read_token())
        self.assertEqual(stat.S_IMODE(self.store.token_path().stat().st_mode), 0o600)
        b = self.store.rotate_token()
        self.assertNotEqual(a, b)
        os.chmod(self.store.token_path(), 0o644)
        with self.assertRaises(GitError):
            self.store.read_token()

    def test_cli_blocks_nonloopback_web(self):
        self.assertEqual(run(["--root", str(self.store.root), "serve-web", "--host", "0.0.0.0"]), 1)


if __name__ == "__main__":
    unittest.main()
