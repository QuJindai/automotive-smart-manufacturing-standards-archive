from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "independent-verifier" / "verify.mjs"


class CrossImplementationContractTests(unittest.TestCase):
    def _verify(self, package_dir: Path):
        completed = subprocess.run(["node", str(NODE), str(package_dir)], capture_output=True, text=True, timeout=20)
        payload = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {}
        return completed, payload

    def test_node_accepts_all_four_goldens(self):
        for name in ("c0-supplier", "c1-lab", "c2-fat-sat", "c3-continuous"):
            with self.subTest(name=name):
                completed, payload = self._verify(ROOT / "examples" / name)
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                self.assertTrue(payload.get("valid"))
                self.assertEqual("PASS", payload.get("overall_decision"))
                self.assertEqual("VALID", payload.get("lifecycle_state"))
                self.assertTrue(payload.get("evidence_hashes_valid"))
                self.assertTrue(payload.get("metrics_valid"))
                self.assertTrue(payload.get("predecessor_rules_valid"))

    def test_node_detects_truthful_material_drift_as_reevaluation_not_fake_failure(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "package"
            shutil.copytree(ROOT / "examples" / "c3-continuous", target)
            path = target / "package.json"
            package = json.loads(path.read_text(encoding="utf-8"))
            package["observed_baseline"]["parameter_hash"] = "0" * 64
            package["declared_material_drift"] = True
            package["claimed_reevaluation_state"] = "REQUIRED"
            package["drifts"] = [{"drift_id":"DRIFT-MATERIAL-001","material":True,"status":"OPEN","description":"synthetic parameter baseline change"}]
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
            completed, payload = self._verify(target)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertTrue(payload.get("valid"))
            self.assertEqual("PASS", payload.get("overall_decision"))
            self.assertEqual("REEVALUATION_REQUIRED", payload.get("lifecycle_state"))

    def test_node_rejects_tampered_effectiveness_metric(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "package"
            shutil.copytree(ROOT / "examples" / "c2-fat-sat", target)
            path = target / "package.json"
            package = json.loads(path.read_text(encoding="utf-8"))
            package["claimed_effectiveness_metrics"]["automation_rate"]["value"] = 0.5
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
            completed, payload = self._verify(target)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(payload.get("valid", True))
            self.assertFalse(payload.get("metrics_valid", True))


if __name__ == "__main__":
    unittest.main()
