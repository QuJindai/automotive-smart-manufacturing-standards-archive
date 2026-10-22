import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PcaeCliContractTests(unittest.TestCase):
    def test_all_four_c0_c3_goldens_produce_twenty_passes(self):
        for level, name in (("C0", "c0-supplier"), ("C1", "c1-lab"), ("C2", "c2-fat-sat"), ("C3", "c3-continuous")):
            with self.subTest(level=level), tempfile.TemporaryDirectory() as td:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "run_reference.py"),
                        "--package",
                        str(ROOT / "examples" / name),
                        "--out",
                        td,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                self.assertIn("CAE_REQUIRED_FAILURES=0", completed.stdout)
                self.assertIn("CAE_PASS=20", completed.stdout)
                for output in (
                    "assessment-summary.json",
                    "criteria-results.json",
                    "effectiveness-metrics.json",
                    "evidence-trace.json",
                    "reevaluation-state.json",
                    "conformity-statement.json",
                    "validator-evidence.json",
                ):
                    self.assertTrue((Path(td) / output).is_file(), output)


if __name__ == "__main__":
    unittest.main()
