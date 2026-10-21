from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import record_hash, valid_rework_package, write_package


ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "independent-verifier" / "verify.mjs"


class CrossImplementationContractTests(unittest.TestCase):
    def _verify(self, package, artifacts):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            write_package(root, package, artifacts)
            completed = subprocess.run(["node", str(NODE), str(root)], capture_output=True, text=True, timeout=20)
            payload = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {}
            return completed, payload

    def test_node_accepts_valid_rework_chain(self):
        package, artifacts = valid_rework_package()
        completed, payload = self._verify(package, artifacts)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertTrue(payload.get("valid"))
        self.assertTrue(payload.get("record_hashes_valid"))
        self.assertTrue(payload.get("lineage_valid"))
        self.assertTrue(payload.get("release_valid"))

    def test_node_rejects_record_tamper(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        package["records"][0]["measurement"]["raw_value"] = 99.0
        completed, payload = self._verify(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))
        self.assertFalse(payload.get("record_hashes_valid", True))

    def test_node_rejects_illegal_release(self):
        package, artifacts = valid_rework_package()
        package = copy.deepcopy(package)
        release = package["records"][-1]
        release["lineage"]["parent_evidence_ids"] = [package["records"][1]["evidence_id"]]
        release["lineage"]["previous_record_hash"] = package["records"][1]["integrity"]["record_sha256"]
        release["integrity"]["record_sha256"] = record_hash(release)
        completed, payload = self._verify(package, artifacts)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))
        self.assertFalse(payload.get("release_valid", True))


if __name__ == "__main__":
    unittest.main()
