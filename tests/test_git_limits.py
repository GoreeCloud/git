"""Safe metadata Git invocation rejects unbounded output and hanging children."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from goreecloud_git.core import GitError, git


class BoundedGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.fake = self.bin / "git"
        self.path = str(self.bin) + os.pathsep + os.environ["PATH"]

    def fake_git(self, source):
        self.fake.write_text("#!" + sys.executable + "\n" + source, encoding="utf-8")
        self.fake.chmod(0o700)

    def invoke(self, **budgets):
        # Fake Git is injected by a test-only mock. The production lookup must
        # never use an arbitrary PATH inherited from the invoking SSH client.
        with patch("goreecloud_git.core.git_binary", return_value=str(self.fake)):
            with patch.dict(os.environ, {"PATH": self.path}, clear=False):
                return git("fake", **budgets)

    def test_output_ceiling_kills_untrusted_producer(self):
        self.fake_git("import os,time\nos.write(1,b'x'*65536)\ntime.sleep(30)\n")
        started = time.monotonic()
        with self.assertRaisesRegex(GitError, "output exceeded"):
            self.invoke(max_output=1024, timeout=5)
        self.assertLess(time.monotonic() - started, 4)

    def test_timeout_without_output_is_bounded(self):
        self.fake_git("import time\ntime.sleep(30)\n")
        started = time.monotonic()
        with self.assertRaisesRegex(GitError, "timed out"):
            self.invoke(max_output=1024, timeout=0.25)
        self.assertLess(time.monotonic() - started, 3)

    def test_exit_code_error_does_not_leak_git_stderr(self):
        self.fake_git("import os,sys\nos.write(2,b'private-path-or-secret')\nsys.exit(9)\n")
        with self.assertRaises(GitError) as ctx:
            self.invoke()
        self.assertIn("exit 9", str(ctx.exception))
        self.assertNotIn("private-path-or-secret", str(ctx.exception))

    def test_sanitized_git_environment(self):
        self.fake_git(
            "import os\n"
            "print(os.environ.get('GIT_CONFIG_NOSYSTEM'))\n"
            "print(os.environ.get('GIT_TRACE', 'absent'))\n"
            "print(os.environ.get('LD_PRELOAD', 'absent'))\n"
            "print(os.environ.get('PYTHONPATH', 'absent'))\n"
            "print(os.environ.get('BASH_ENV', 'absent'))\n"
            "print(os.environ.get('PATH'))\n"
        )
        with patch.dict(os.environ, {
            "GIT_TRACE": "danger", "GIT_CONFIG_COUNT": "1",
            "LD_PRELOAD": "/tmp/untrusted.so", "PYTHONPATH": "/tmp/inject",
            "BASH_ENV": "/tmp/inject", "PATH": self.path,
        }, clear=False):
            output = self.invoke()
        self.assertEqual(output, "1\nabsent\nabsent\nabsent\nabsent\n" + os.defpath)

    def test_untrusted_path_cannot_replace_git_binary(self):
        self.fake_git("print('UNTRUSTED EXECUTABLE')\n")
        with patch.dict(os.environ, {"PATH": self.path}, clear=False):
            self.assertTrue(git("--version").startswith("git version"))

    def test_real_git_version_succeeds(self):
        self.assertTrue(git("--version").startswith("git version"))

    def test_invalid_output_and_timeout_budgets_rejected(self):
        for opts in (
            {"max_output": 0}, {"max_output": 1048577}, {"timeout": 0},
        ):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                git("--version", **opts)


if __name__ == "__main__":
    unittest.main()
