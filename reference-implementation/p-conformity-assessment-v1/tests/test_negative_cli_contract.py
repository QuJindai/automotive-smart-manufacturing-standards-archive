from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NegativeCliContractTests(unittest.TestCase):
    def test_negative_and_lifecycle_registry_has_zero_false_passes(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "negative-summary.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "run_negative_cases.py"), "--out", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("CAE_NEGATIVE_CASES=18", completed.stdout)
            self.assertIn("CAE_NEGATIVE_FALSE_PASSES=0", completed.stdout)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(18, data["case_count"])
            self.assertEqual(0, data["false_pass_count"])
            self.assertTrue(all(not row["false_pass"] for row in data["cases"]))
            lifecycle_cases = {row["case_id"]: row for row in data["cases"] if row.get("expected_lifecycle_state")}
            self.assertEqual("REEVALUATION_REQUIRED", lifecycle_cases["NEG-MATERIAL-DRIFT"]["observed_lifecycle_state"])
            self.assertEqual("EXPIRED", lifecycle_cases["NEG-EXPIRED"]["observed_lifecycle_state"])


if __name__ == "__main__":
    unittest.main()
