"""Integration tests use real Git but isolated temporary private directories."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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

    def test_create_is_atomic_under_concurrent_requests(self):
        def attempt(_):
            try:
                self.store.create("same-name")
                return True
            except GitError as exc:
                self.assertIn("already exists", str(exc))
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(12)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(outcomes.count(False), 11)
        self.assertEqual(self.store.names(), ["same-name"])
        self.assertEqual(self.store.info("same-name")["commits"], 0)
        self.assertEqual(stat.S_IMODE(self.store.path("same-name").stat().st_mode), 0o700)

    def test_create_never_overwrites_existing_directory(self):
        existing = self.store.path("occupied")
        existing.mkdir(mode=0o700)
        sentinel = existing / "leave-me"
        sentinel.write_text("original data")
        with self.assertRaises(GitError):
            self.store.create("occupied")
        self.assertEqual(sentinel.read_text(), "original data")

    def test_failed_creation_preserves_private_reserved_path(self):
        with patch("goreecloud_git.core.git", side_effect=GitError("test init failed")):
            with self.assertRaises(GitError):
                self.store.create("broken")
        reserved = self.store.path("broken")
        self.assertTrue(reserved.is_dir())
        self.assertEqual(stat.S_IMODE(reserved.stat().st_mode), 0o700)
        self.assertEqual(self.store.names(), [])  # incomplete entries not advertised
        with self.assertRaises(GitError):
            self.store.create("broken")  # never silently reuse unknown content

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

    def test_exposed_repository_directory_is_rejected_without_repair(self):
        path = self.store.create("example")
        os.chmod(path, 0o755)
        with self.assertRaises(GitError):
            self.store.existing("example")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
        self.store.create("healthy")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(["--root", str(self.store.root), "verify-all"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL: example", err.getvalue())
        self.assertIn("PASS: healthy", out.getvalue())
        self.assertIn("Integrity sweep: 1/2 passed.", out.getvalue())

    def test_control_file_link_is_rejected(self):
        bare = self.store.create("linked")
        source = bare / "config"
        original = bare / "config.saved"
        source.rename(original)
        source.symlink_to(original)
        with self.assertRaises(GitError):
            self.store.existing("linked")
        self.assertTrue(source.is_symlink())

    def test_must_not_repair_insecure_existing_root(self):
        os.chmod(self.store.root, 0o755)
        with self.assertRaises(GitError):
            self.store.init()
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o755)

    def test_storage_root_rejects_foreign_owner_before_creating_any_repo(self):
        current_uid = os.geteuid()
        before = self.store.root.stat()
        with patch("goreecloud_git.core.os.geteuid", return_value=current_uid + 100001):
            with self.assertRaisesRegex(GitError, "current account"):
                self.store.ready()
            with self.assertRaisesRegex(GitError, "current account"):
                self.store.create("not-created")
        self.assertFalse(self.store.path("not-created").exists())
        self.assertEqual(self.store.root.stat().st_uid, before.st_uid)
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o700)

    def test_repository_rejects_foreign_owner_without_mutating_it(self):
        bare = self.store.create("owned")
        real_lstat = Path.lstat

        def foreign_repo_owner(path, *args, **kwargs):
            metadata = real_lstat(path, *args, **kwargs)
            if path == bare:
                fields = list(metadata)
                fields[4] = os.geteuid() + 100001
                return os.stat_result(fields)
            return metadata

        with patch("pathlib.Path.lstat", new=foreign_repo_owner):
            with self.assertRaisesRegex(GitError, "current account"):
                self.store.existing("owned")
            self.assertIn("owned", self.store.inventory_issues())
        self.assertTrue(bare.is_dir())
        self.assertEqual(bare.stat().st_uid, os.geteuid())
        self.store.verify("owned")

    def test_foreign_owned_token_is_not_read_or_replaced(self):
        token = self.store.rotate_token()
        target = self.store.token_path()
        real_lstat = Path.lstat

        def foreign_token_owner(path, *args, **kwargs):
            metadata = real_lstat(path, *args, **kwargs)
            if path == target:
                fields = list(metadata)
                fields[4] = os.geteuid() + 100001
                return os.stat_result(fields)
            return metadata

        real_fstat = os.fstat

        def foreign_open_file_owner(fd):
            fields = list(real_fstat(fd))
            fields[4] = os.geteuid() + 100001
            return os.stat_result(fields)

        # Reads validate the opened descriptor, not the pathname; rotation
        # independently checks the existing pathname before replacing it.
        with patch("goreecloud_git.core.os.fstat", side_effect=foreign_open_file_owner):
            with self.assertRaisesRegex(GitError, "Missing or exposed web token"):
                self.store.read_token()
        with patch("pathlib.Path.lstat", new=foreign_token_owner):
            with self.assertRaisesRegex(GitError, "foreign-owned web token"):
                self.store.rotate_token()
        self.assertEqual(self.store.read_token(), token)

    def test_web_token_read_denies_path_swap_to_symlink(self):
        valid = self.store.rotate_token()
        path = self.store.token_path()
        protected = Path(self.tmp.name) / "outside-token"
        protected.write_text(valid + "\n")
        real_open = os.open

        def swap_before_open(name, flags, *args, **kwargs):
            if Path(name) == path:
                path.unlink()
                path.symlink_to(protected)
            return real_open(name, flags, *args, **kwargs)

        with patch("goreecloud_git.core.os.open", side_effect=swap_before_open):
            with self.assertRaisesRegex(GitError, "Missing or exposed web token"):
                self.store.read_token()
        self.assertTrue(path.is_symlink())
        self.assertEqual(protected.read_text().strip(), valid)

    def test_web_token_read_denies_special_files_without_blocking(self):
        self.store.rotate_token()
        path = self.store.token_path()
        path.unlink()
        os.mkfifo(path, mode=0o600)
        with self.assertRaisesRegex(GitError, "Missing or exposed web token"):
            self.store.read_token()
        self.assertTrue(stat.S_ISFIFO(path.lstat().st_mode))

    def test_web_token_read_has_strict_size_and_encoding_limits(self):
        self.store.rotate_token()
        path = self.store.token_path()
        path.write_bytes(b"x" * 5000)
        with self.assertRaisesRegex(GitError, "Invalid web token"):
            self.store.read_token()
        path.write_bytes(b"x" * 45 + b"\xff")
        with self.assertRaisesRegex(GitError, "Invalid web token"):
            self.store.read_token()
        path.write_text("safe-" + "a" * 42 + "\n")
        self.assertEqual(self.store.read_token(), "safe-" + "a" * 42)

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

    def test_doctor_reports_incomplete_reservation_without_repair(self):
        self.store.create("healthy")
        orphan = self.store.repos / "unfinished.git"
        orphan.mkdir(mode=0o700)
        self.assertNotIn("unfinished", self.store.names())
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = run(["--root", str(self.store.root), "doctor"])
        self.assertEqual(status, 1)
        self.assertIn("unfinished", err.getvalue())
        self.assertNotIn("healthy", err.getvalue())
        self.assertTrue(orphan.is_dir())
        self.assertEqual(stat.S_IMODE(orphan.stat().st_mode), 0o700)

    def test_doctor_reports_unsafe_directory_and_symlink(self):
        exposed = self.store.create("exposed")
        os.chmod(exposed, 0o755)
        link = self.store.repos / "link.git"
        link.symlink_to(exposed, target_is_directory=True)
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = run(["--root", str(self.store.root), "doctor"])
        self.assertEqual(status, 1)
        self.assertIn("exposed", err.getvalue())
        self.assertIn("link", err.getvalue())
        self.assertTrue(link.is_symlink())
        self.assertEqual(stat.S_IMODE(exposed.stat().st_mode), 0o755)

    def test_doctor_healthy_inventory_does_not_run_fsck(self):
        self.store.create("ready")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = run(["--root", str(self.store.root), "doctor"])
        self.assertEqual(status, 0)
        self.assertIn("basic access checks passed", out.getvalue())
        self.assertNotIn("fsck", err.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_cli_verify(self):
        self.store.create("project")
        self.assertEqual(run(["--root", str(self.store.root), "verify", "project"]), 0)

    def test_cli_verify_all_healthy_repositories(self):
        self.store.create("alpha")
        self.store.create("beta")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(["--root", str(self.store.root), "verify-all"])
        self.assertEqual(code, 0)
        self.assertIn("PASS: alpha", out.getvalue())
        self.assertIn("PASS: beta", out.getvalue())
        self.assertIn("Integrity sweep: 2/2 passed.", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_cli_verify_all_continues_after_corruption(self):
        corrupt = self.store.create("alpha")
        self.store.create("beta")
        (corrupt / "refs/heads/main").write_text("not-a-valid-object-id\n")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(["--root", str(self.store.root), "verify-all"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL: alpha", err.getvalue())
        self.assertIn("PASS: beta", out.getvalue())
        self.assertIn("Integrity sweep: 1/2 passed.", out.getvalue())
        self.assertNotIn(str(self.store.root), err.getvalue())

    def test_cli_verify_all_empty_root_is_explicit(self):
        out = StringIO()
        with redirect_stdout(out):
            code = run(["--root", str(self.store.root), "verify-all"])
        self.assertEqual(code, 0)
        self.assertIn("No complete private repositories to verify.", out.getvalue())
        self.assertIn("Integrity sweep: 0/0 passed.", out.getvalue())

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
