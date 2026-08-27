from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NegativeCliContractTests(unittest.TestCase):
    def test_negative_case_runner_writes_truthful_summary(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "negative-summary.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "run_negative_cases.py"), "--out", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("ME_NEGATIVE_CASES=14", completed.stdout)
            self.assertIn("ME_NEGATIVE_FALSE_PASSES=0", completed.stdout)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(14, data["case_count"])
            self.assertEqual(0, data["false_pass_count"])
            self.assertTrue(all(not row["false_pass"] for row in data["cases"]))
            self.assertTrue(all(row["observed_result"] in {"FAIL", "BLOCKED"} for row in data["cases"]))


if __name__ == "__main__":
    unittest.main()
