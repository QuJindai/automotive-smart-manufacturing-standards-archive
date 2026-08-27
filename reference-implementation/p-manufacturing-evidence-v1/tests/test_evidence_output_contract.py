from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EvidenceOutputContractTests(unittest.TestCase):
    def test_validator_evidence_reuses_common_bundle_vocabulary(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "run_reference.py"), "--package", str(ROOT / "examples" / "eol-rework-retest"), "--out", str(out)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            expected = {
                "validation-summary.json",
                "conformance-results.json",
                "trace-graph.json",
                "trace-query-release.json",
                "evidence-package-manifest.json",
                "validator-evidence.json",
            }
            self.assertEqual(expected, {p.name for p in out.iterdir() if p.is_file()})
            evidence = json.loads((out / "validator-evidence.json").read_text(encoding="utf-8"))
            self.assertEqual("1.0", evidence["schema_version"])
            self.assertEqual("P-ME-EOL-1.0", evidence["profile_version"])
            self.assertFalse(evidence["environment"]["certification_claim"])
            self.assertEqual([f"ME-T{i:03d}" for i in range(1, 19)], [r["test_id"] for r in evidence["test_results"]])
            self.assertTrue(all(r["result"] == "PASS" for r in evidence["test_results"]))
            refs = evidence["environment"]["output_artifacts"]
            self.assertEqual(5, len(refs))
            self.assertTrue(all(len(ref["sha256"]) == 64 for ref in refs))


if __name__ == "__main__":
    unittest.main()
