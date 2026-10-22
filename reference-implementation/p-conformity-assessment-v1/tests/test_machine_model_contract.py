import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


class MachineModelContractTests(unittest.TestCase):
    def test_p0_08_machine_assets_define_twenty_required_tests_and_c0_c3(self):
        schema_path = REPO / "machine-readable" / "p0-08" / "conformity-assessment-v1.schema.json"
        profile_path = REPO / "machine-readable" / "p0-08" / "automotive-profile-v1.json"
        cac_path = REPO / "machine-readable" / "p0-08" / "conformance-criteria-v1.json"
        self.assertTrue(schema_path.is_file(), schema_path)
        self.assertTrue(profile_path.is_file(), profile_path)
        self.assertTrue(cac_path.is_file(), cac_path)

        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        cac = json.loads(cac_path.read_text(encoding="utf-8"))
        expected = [f"CAE-T{i:03d}" for i in range(1, 21)]
        self.assertEqual("P-CAE-AUTO-R14", profile["profile_id"])
        self.assertEqual(["C0", "C1", "C2", "C3"], profile["assessment_levels"])
        self.assertEqual(expected, profile["required_conformance_tests"])
        self.assertEqual(expected, [row["test_id"] for row in cac["criteria"]])
        self.assertTrue(all(row["required"] is True for row in cac["criteria"]))
        for row in cac["criteria"]:
            for field in ("requirement_id", "proof_type", "test_id", "automation_flag", "applicability_rule", "decision_rule", "evidence_requirements"):
                self.assertIn(field, row)

    def test_common_evidence_schema_accepts_cae_namespace(self):
        common = (REPO / "machine-readable" / "v1" / "evidence.schema.json").read_text(encoding="utf-8")
        self.assertIn("CAE", common)


if __name__ == "__main__":
    unittest.main()
