"""OpenSSH forced-command transport rejects unexpected commands and scope leaks."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from goreecloud_git.cli import run
from goreecloud_git.core import GitError, Store
from goreecloud_git.ssh import parse_request, serve_ssh


class SSHTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "private")
        self.store.init()
        self.store.create("first")
        self.store.create("second")

    def test_upload_pack_permitted_for_named_repository(self):
        path = self.store.path("first")
        self.assertEqual(parse_request(self.store, f"git-upload-pack '{path}'", "first"),
                         ("git-upload-pack", path))
        self.assertEqual(parse_request(self.store, "git-upload-pack first.git", "first"),
                         ("git-upload-pack", path))

    def test_receive_pack_is_opt_in(self):
        with self.assertRaises(GitError):
            parse_request(self.store, "git-receive-pack first.git", "first")
        self.assertEqual(parse_request(self.store, "git-receive-pack first.git", "first", True)[0],
                         "git-receive-pack")

    def test_repo_access_is_scoped_to_one_key(self):
        for target in ("second.git", "/tmp/other.git", "../first.git",
                       "first.git/", "./first.git", "-flag", "/etc/passwd"):
            with self.subTest(target=target), self.assertRaises(GitError):
                parse_request(self.store, f"git-upload-pack '{target}'", "first")

    def test_no_arbitrary_ssh_commands_or_injection(self):
        requests = [None, "", "ls", "sh -c id", "git-upload-pack", "git-upload-pack first.git --upload-pack=evil",
                    "git-upload-pack 'first.git'; id", "git-upload-pack first.git\nwhoami",
                    "git-receive-pack 'first.git' && id", "git-upload-pack first.git\x00x",
                    "git-upload-pack 'unterminated", "git-upload-pack " + "x" * 2050]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(GitError):
                parse_request(self.store, request, "first")

    def test_missing_repository_and_bad_scopes_fail_closed(self):
        for name in ("missing", "..", "first.git", "bad/name"):
            with self.subTest(name=name), self.assertRaises((GitError, ValueError)):
                parse_request(self.store, "git-upload-pack first.git", name)

    def test_cli_requires_original_command(self):
        prior = os.environ.pop("SSH_ORIGINAL_COMMAND", None)
        try:
            self.assertEqual(run(["--root", str(self.store.root), "serve-ssh", "--repo", "first"]), 1)
        finally:
            if prior is not None:
                os.environ["SSH_ORIGINAL_COMMAND"] = prior

    def test_git_wire_advertises_refs_without_a_shell(self):
        working = Path(self.temp.name) / "working"
        subprocess.run(["git", "init", "-b", "main", str(working)], check=True, capture_output=True)
        (working / "file.txt").write_text("test\n")
        subprocess.run(["git", "-C", str(working), "add", "file.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "-c", "user.name=Tester",
                        "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "push", str(self.store.path("first")), "main"],
                       check=True, capture_output=True)
        shim = Path(self.temp.name) / "ssh-shim"
        shim.write_text(
            "#!/usr/bin/env python3\n"
            "import os,sys\n"
            "os.environ['SSH_ORIGINAL_COMMAND'] = sys.argv[-1]\n"
            "os.execv(sys.executable, [sys.executable, '-m', 'goreecloud_git.cli', "
            "'--root', " + repr(str(self.store.root)) + ", 'serve-ssh', '--repo', 'first'])\n"
        )
        shim.chmod(0o700)
        env = dict(os.environ, GIT_SSH=str(shim), GIT_SSH_VARIANT="simple",
                   PYTHONPATH=str(Path(__file__).parents[1] / "src"))
        remote = "ssh://git@offline.invalid" + str(self.store.path("first"))
        result = subprocess.run(["git", "ls-remote", remote], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("refs/heads/main", result.stdout)
        clone = Path(self.temp.name) / "clone"
        result = subprocess.run(["git", "clone", remote, str(clone)], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / "file.txt").read_text(), "test\n")
        result = subprocess.run(["git", "-C", str(working), "push", remote, "main"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, "read-only key unexpectedly permitted push")

        writable = Path(self.temp.name) / "ssh-shim-write"
        writable.write_text(shim.read_text().replace(
            "'--repo', 'first'])", "'--repo', 'first', '--allow-push'])"))
        writable.chmod(0o700)
        (working / "file.txt").write_text("updated test\n")
        subprocess.run(["git", "-C", str(working), "add", "file.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(working), "-c", "user.name=Tester",
                        "-c", "user.email=test@example.invalid", "commit", "-m", "second"],
                       check=True, capture_output=True)
        writable_env = dict(env, GIT_SSH=str(writable))
        result = subprocess.run(["git", "-C", str(working), "push", remote, "main"],
                                env=writable_env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.store.info("first")["commits"], 2)


if __name__ == "__main__":
    unittest.main()
