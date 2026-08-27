import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PmeCliContractTests(unittest.TestCase):
    def test_golden_eol_package_produces_eighteen_passes(self):
        package_dir = ROOT / "examples" / "eol-single-pass"
        with tempfile.TemporaryDirectory() as td:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "run_reference.py"), "--package", str(package_dir), "--out", td],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("ME_REQUIRED_FAILURES=0", completed.stdout)
            self.assertIn("ME_PASS=18", completed.stdout)
            for name in (
                "validation-summary.json",
                "conformance-results.json",
                "trace-graph.json",
                "trace-query-release.json",
                "evidence-package-manifest.json",
                "validator-evidence.json",
            ):
                self.assertTrue((Path(td) / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
