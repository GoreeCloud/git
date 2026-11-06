"""Git execution environment is confined to an explicit allowlist."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goreecloud_git.core import Store
from goreecloud_git.git_environment import git_binary, git_environment
from goreecloud_git.ssh import serve_ssh


class GitEnvironmentTests(unittest.TestCase):
    def test_untrusted_parent_values_are_not_inherited(self):
        values = {"PATH": "/tmp/alternate", "LD_PRELOAD": "/tmp/library",
                  "PYTHONPATH": "/tmp/module", "BASH_ENV": "/tmp/shell",
                  "GIT_TRACE": "true", "GIT_CONFIG_COUNT": "1"}
        with patch.dict(os.environ, values, clear=False):
            env = git_environment()
        self.assertEqual(env["PATH"], os.defpath)
        self.assertEqual(env["LC_ALL"], "C")
        for name in ("LD_PRELOAD", "PYTHONPATH", "BASH_ENV",
                     "GIT_TRACE", "GIT_CONFIG_COUNT"):
            self.assertNotIn(name, env)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")

    def test_ssh_protocol_v2_requires_exact_opt_in(self):
        for original, expected in (("version=2", True), ("version=2:option=1", False),
                                   ("version=1", False), ("unexpected", False)):
            with self.subTest(original=original):
                with patch.dict(os.environ, {"GIT_PROTOCOL": original}):
                    env = git_environment(allow_ssh_protocol=True)
                    self.assertEqual(env.get("GIT_PROTOCOL") == "version=2", expected)
                    self.assertNotIn("GIT_PROTOCOL", git_environment())

    def test_native_ssh_transport_uses_same_restricted_environment(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "private")
            store.init()
            store.create("first")
            overrides = {"SSH_ORIGINAL_COMMAND": "git-upload-pack first.git",
                         "PATH": td, "LD_PRELOAD": "/tmp/library",
                         "GIT_CONFIG_COUNT": "1", "GIT_PROTOCOL": "version=2"}
            with patch.dict(os.environ, overrides, clear=False):
                with patch("goreecloud_git.ssh._run_transport", return_value=0) as launched:
                    self.assertEqual(serve_ssh(store, "first"), 0)
            argv, env, *_ = launched.call_args.args
            self.assertEqual(argv[0], git_binary())
            self.assertEqual(argv[1:], ["upload-pack", str(store.path("first"))])
            self.assertEqual(env["GIT_PROTOCOL"], "version=2")
            self.assertEqual(env["PATH"], os.defpath)
            self.assertNotIn("LD_PRELOAD", env)
            self.assertNotIn("GIT_CONFIG_COUNT", env)
            self.assertNotIn("SSH_ORIGINAL_COMMAND", env)


if __name__ == "__main__":
    unittest.main()
