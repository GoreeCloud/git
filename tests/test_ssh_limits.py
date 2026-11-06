"""Bounded native SSH transport: deterministic POSIX-only regression tests."""
import os
from pathlib import Path
import resource
import sys
import tempfile
import unittest

from goreecloud_git.cli import run
from goreecloud_git.core import Store, GitError
from goreecloud_git.ssh import (
    DEFAULT_CPU_SECONDS, DEFAULT_MEMORY_MIB, DEFAULT_WALL_SECONDS,
    _run_transport, validate_limits,
)


@unittest.skipUnless(os.name == "posix", "POSIX resource limits")
class SSHResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "private")
        self.store.init()
        self.store.create("example")

    def test_budgets_reject_invalid_ranges_and_types(self):
        validate_limits(DEFAULT_WALL_SECONDS, DEFAULT_CPU_SECONDS, DEFAULT_MEMORY_MIB)
        for budgets in (
            (0, 300, 2048), (7201, 300, 2048),
            (600, 0, 2048), (600, 3601, 2048),
            (600, 300, 127), (600, 300, 16385),
            (True, 300, 2048), (600, 1.2, 2048),
        ):
            with self.subTest(budgets=budgets), self.assertRaises(ValueError):
                validate_limits(*budgets)

    def test_child_gets_budgets_without_changing_parent(self):
        original_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        original_as = resource.getrlimit(resource.RLIMIT_AS)
        dest = Path(self.tmp.name) / "bounds.txt"
        script = (
            "import resource,sys\n"
            "cpu=resource.getrlimit(resource.RLIMIT_CPU)\n"
            "mem=resource.getrlimit(resource.RLIMIT_AS)\n"
            "open(sys.argv[1],'w').write(f'{cpu[0]} {mem[0]}')\n"
        )
        status = _run_transport([sys.executable, "-c", script, str(dest)],
                                dict(os.environ), 5, 3, 256)
        self.assertEqual(status, 0)
        self.assertEqual(dest.read_text(), f"3 {256 * 1024 * 1024}")
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CPU), original_cpu)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_AS), original_as)

    def test_wall_timeout_reaps_child_and_reports_failure(self):
        # An SSH client that never sends more data cannot hold an unbounded worker.
        with self.assertRaisesRegex(GitError, "timed out"):
            _run_transport([sys.executable, "-c", "import time;time.sleep(30)"],
                           dict(os.environ), 1, 5, 256)

    def test_exit_code_propagates(self):
        status = _run_transport([sys.executable, "-c", "raise SystemExit(7)"],
                                dict(os.environ), 5, 5, 256)
        self.assertEqual(status, 7)

    def test_invalid_limits_rejected_before_ssh_operation(self):
        self.assertEqual(run(["--root", str(self.store.root), "serve-ssh",
                              "--repo", "example", "--wall-seconds", "0"]), 1)
        self.assertEqual(run(["--root", str(self.store.root), "serve-ssh",
                              "--repo", "example", "--memory-mib", "0"]), 1)


if __name__ == "__main__":
    unittest.main()
