from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import record_hash, valid_rework_package, write_package


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def run_reference(package_dir: Path, out_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "run_reference.py"), "--package", str(package_dir), "--out", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=20,
    )


class PmeConformanceContractTests(unittest.TestCase):
    def _run_package(self, package, artifacts):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "package"
        out = Path(td.name) / "out"
        write_package(root, package, artifacts)
        return run_reference(root, out), out

    def test_valid_rework_retest_release_chain_passes_all_eighteen(self):
        package, artifacts = valid_rework_package()
        completed, _ = self._run_package(package, artifacts)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("ME_REQUIRED_FAILURES=0", completed.stdout)
        self.assertIn("ME_PASS=18", completed.stdout)

    def test_raw_artifact_tamper_fails_me_t009(self):
        package, artifacts = valid_rework_package()
        artifacts = dict(artifacts)
        artifacts[next(iter(artifacts))] = b'{"tampered":true}'
        completed, _ = self._run_package(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ME-T009", completed.stdout)

    def test_record_tamper_fails_me_t010(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        package["records"][0]["measurement"]["raw_value"] = 99.0
        completed, _ = self._run_package(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ME-T010", completed.stdout)

    def test_broken_parent_hash_fails_me_t012(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        package["records"][2]["lineage"]["previous_record_hash"] = "0" * 64
        package["records"][2]["integrity"]["record_sha256"] = record_hash(package["records"][2])
        completed, _ = self._run_package(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ME-T012", completed.stdout)

    def test_attempt_gap_fails_me_t013(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        package["records"][2]["lineage"]["attempt_no"] = 3
        package["records"][2]["integrity"]["record_sha256"] = record_hash(package["records"][2])
        package["records"][3]["lineage"]["attempt_no"] = 3
        package["records"][3]["integrity"]["record_sha256"] = record_hash(package["records"][3])
        completed, _ = self._run_package(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ME-T013", completed.stdout)

    def test_illegal_release_without_pass_parent_fails_me_t015(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        release = package["records"][-1]
        release["lineage"]["parent_evidence_ids"] = [package["records"][1]["evidence_id"]]
        release["lineage"]["previous_record_hash"] = package["records"][1]["integrity"]["record_sha256"]
        release["integrity"]["record_sha256"] = record_hash(release)
        completed, _ = self._run_package(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ME-T015", completed.stdout)

    def test_generic_evidence_schema_accepts_me_test_namespace(self):
        schema_text = (REPO / "machine-readable" / "v1" / "evidence.schema.json").read_text(encoding="utf-8")
        self.assertIn("AAS|AI|ME", schema_text)


if __name__ == "__main__":
    unittest.main()
