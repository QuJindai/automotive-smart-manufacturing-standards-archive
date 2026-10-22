from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pcae.evaluator import validate_package


ROOT = Path(__file__).resolve().parents[1]


class LifecycleContractTests(unittest.TestCase):
    def _copy_package(self, name: str, mutate) -> Path:
        source = ROOT / "examples" / name
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        target = Path(td.name) / "package"
        import shutil
        shutil.copytree(source, target)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        mutate(package)
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def test_truthfully_declared_material_drift_requires_reevaluation_without_becoming_data_integrity_failure(self):
        def mutate(package):
            package["observed_baseline"]["parameter_hash"] = "0" * 64
            package["declared_material_drift"] = True
            package["claimed_reevaluation_state"] = "REQUIRED"
            package["drifts"] = [{
                "drift_id": "DRIFT-MATERIAL-001",
                "material": True,
                "status": "OPEN",
                "description": "synthetic parameter baseline change",
            }]

        run = validate_package(self._copy_package("c3-continuous", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("PASS", by_id["CAE-T013"].result, by_id["CAE-T013"])
        self.assertEqual("PASS", by_id["CAE-T014"].result, by_id["CAE-T014"])
        self.assertEqual("PASS", by_id["CAE-T015"].result, by_id["CAE-T015"])
        self.assertEqual("REEVALUATION_REQUIRED", run.lifecycle_state)
        self.assertEqual("PASS", run.overall_decision)

    def test_undeclared_material_drift_is_a_conformance_failure(self):
        def mutate(package):
            package["observed_baseline"]["parameter_hash"] = "0" * 64
            package["declared_material_drift"] = False
            package["claimed_reevaluation_state"] = "NOT_REQUIRED"

        run = validate_package(self._copy_package("c3-continuous", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T014"].result)
        self.assertEqual("FAIL", by_id["CAE-T015"].result)
        self.assertEqual("FAIL", run.overall_decision)


if __name__ == "__main__":
    unittest.main()
