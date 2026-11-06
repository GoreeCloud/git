"""Pure parser regression tests for the optional OpenSSH config smoke test."""
from pathlib import Path
import runpy
import unittest


class SSHConfigSmokeParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[1] / "scripts" / "smoke-sshd-config.py"
        namespace = runpy.run_path(str(script))
        cls.required = namespace["REQUIRED"]
        cls.validate = staticmethod(namespace["validate_output"])

    def test_expected_config_values_accepted(self):
        lines = "\n".join(f"{k} {v}" for k, v in self.required.items())
        self.validate(lines)

    def test_missing_or_disabled_restrictions_rejected(self):
        lines = dict(self.required)
        lines["passwordauthentication"] = "yes"
        with self.assertRaises(RuntimeError):
            self.validate("\n".join(f"{k} {v}" for k, v in lines.items()))
        del lines["permittty"]
        with self.assertRaises(RuntimeError):
            self.validate("\n".join(f"{k} {v}" for k, v in lines.items()))


if __name__ == "__main__":
    unittest.main()
