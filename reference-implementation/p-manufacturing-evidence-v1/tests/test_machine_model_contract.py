from __future__ import annotations

import json
import unittest
from pathlib import Path

from support import PARAMETER_HASH, PARAMETER_SET_ID


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


class MachineModelContractTests(unittest.TestCase):
    def test_record_model_uses_typed_nested_definitions(self):
        schema = json.loads((REPO / "machine-readable" / "p0-06" / "manufacturing-evidence-v1.schema.json").read_text(encoding="utf-8"))
        defs = schema["$defs"]
        record = defs["record"]
        expected_refs = {
            "subject": "#/$defs/subject",
            "source": "#/$defs/source",
            "process_context": "#/$defs/process_context",
            "measurement": "#/$defs/measurement",
            "execution_context": "#/$defs/execution_context",
            "time": "#/$defs/time",
            "lineage": "#/$defs/lineage",
            "raw_artifacts": "#/$defs/raw_artifacts",
            "disposition": "#/$defs/disposition",
            "integrity": "#/$defs/integrity",
        }
        for field, ref in expected_refs.items():
            self.assertEqual(ref, record["properties"][field].get("$ref"), field)
        self.assertEqual(["system_id", "equipment_id", "source_record_id"], defs["source"]["required"])
        self.assertIn("parameter_hash", defs["execution_context"]["required"])
        self.assertIn("uncertainty", defs["measurement"]["required"])
        self.assertIn("previous_record_hash", defs["lineage"]["required"])
        self.assertEqual("^[a-f0-9]{64}$", defs["sha256"]["pattern"])

    def test_profile_freezes_parameter_set_binding_and_eighteen_tests(self):
        profile = json.loads((REPO / "machine-readable" / "p0-06" / "eol-profile-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(PARAMETER_SET_ID, profile["parameter_set"]["id"])
        self.assertEqual(PARAMETER_HASH, profile["parameter_set"]["sha256"])
        self.assertEqual([f"ME-T{i:03d}" for i in range(1, 19)], profile["required_conformance_tests"])


if __name__ == "__main__":
    unittest.main()
