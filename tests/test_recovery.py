"""Synthetic offline restore rehearsal: no network, no production repositories."""
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

from goreecloud_git.core import Store


def command(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True,
                            text=True, timeout=20)
    return result.stdout.strip()


class RecoverySmokeTests(unittest.TestCase):
    def test_quiesced_private_snapshot_restores_to_new_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Store(Path(tmp) / "original")
            original.init()
            bare = original.create("sample")
            working = Path(tmp) / "working"
            command("init", "-b", "main", str(working))
            (working / "data.txt").write_text("Private repository fixture\n", encoding="utf-8")
            command("-C", str(working), "add", "data.txt")
            command("-C", str(working), "-c", "user.name=RecoveryTest",
                    "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
            command("-C", str(working), "push", str(bare), "main")
            original.verify("sample")
            head = command("--git-dir", str(bare), "rev-parse", "refs/heads/main")

            # This is a disposable, quiesced *filesystem test only*. In real
            # deployments GoreeCloud Backup/Kopia must encrypt the snapshot.
            snapshot = Path(tmp) / "offline-restored"
            shutil.copytree(original.root, snapshot, symlinks=True)
            restored = Store(snapshot)
            restored.verify("sample")
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(restored.repos.stat().st_mode), 0o700)
            self.assertEqual(command("--git-dir", str(restored.path("sample")), "rev-parse",
                                     "refs/heads/main"), head)
            self.assertEqual(command("--git-dir", str(restored.path("sample")), "config",
                                     "--get", "receive.denyDeletes"), "true")
            self.assertEqual(command("--git-dir", str(restored.path("sample")), "config",
                                     "--get", "receive.denyNonFastForwards"), "true")
            client = Path(tmp) / "restored-client"
            command("clone", str(restored.path("sample")), str(client))
            self.assertEqual((client / "data.txt").read_text(encoding="utf-8"),
                             "Private repository fixture\n")

    def test_restore_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Store(Path(tmp) / "source")
            source.init()
            source.create("repository")
            target = Path(tmp) / "already-present"
            target.mkdir()
            (target / "sentinel").write_text("preserve me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                shutil.copytree(source.root, target)
            self.assertEqual((target / "sentinel").read_text(encoding="utf-8"), "preserve me")


if __name__ == "__main__":
    unittest.main()
