from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pcae.evaluator import validate_package


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


class ReviewHardeningContractTests(unittest.TestCase):
    def _mutated(self, name: str, mutate) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        target = Path(td.name) / "package"
        shutil.copytree(ROOT / "examples" / name, target)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        mutate(package)
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def test_automation_count_is_derived_from_cac_not_self_declared(self):
        def mutate(package):
            package["execution_summary"]["automatable_required"] = 19
            package["execution_summary"]["automated_executed"] = 19
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T005"].result)

    def test_not_applicable_cannot_self_authorize(self):
        def mutate(package):
            package["not_applicable"] = [{
                "test_id": "CAE-T010",
                "permitted": True,
                "justification": "package self-declared permission must not be authoritative",
            }]
        run = validate_package(self._mutated("c1-lab", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T007"].result)

    def test_assurance_chain_is_hash_bound_to_predecessor_assessment_evidence(self):
        for name in ("c1-lab", "c2-fat-sat", "c3-continuous"):
            with self.subTest(name=name):
                package_dir = ROOT / "examples" / name
                package = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
                refs = {row["evidence_id"]: row for row in package["evidence_refs"]}
                self.assertTrue(package["assurance_chain"])
                for predecessor in package["assurance_chain"]:
                    evidence_id = predecessor.get("evidence_id")
                    self.assertTrue(evidence_id, predecessor)
                    self.assertIn(evidence_id, refs)
                    self.assertEqual("ATTESTATION", refs[evidence_id]["proof_type"])
                    proof = json.loads((package_dir / refs[evidence_id]["uri"]).read_text(encoding="utf-8"))
                    self.assertEqual(predecessor["assessment_id"], proof["assessment_id"])
                    self.assertEqual(predecessor["level"], proof["assessment_level"])
                    self.assertEqual(predecessor["decision"], proof["decision"])
                    self.assertEqual(predecessor["lifecycle_state"], proof["lifecycle_state"])
                    self.assertEqual(predecessor["valid_until"], proof["valid_until"])
                    self.assertFalse(proof["certification_claim"])

    def test_expired_predecessor_cannot_be_inherited(self):
        def mutate(package):
            for row in package["assurance_chain"]:
                if row["level"] == "C1":
                    row["valid_until"] = "2026-07-31T00:00:00Z"
        run = validate_package(self._mutated("c2-fat-sat", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T011"].result)

    def test_spoofed_p0_06_source_stage_does_not_satisfy_c2(self):
        def mutate(package):
            removed = {row["evidence_id"] for row in package["evidence_refs"] if row.get("source_stage") == "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE"}
            package["evidence_refs"] = [row for row in package["evidence_refs"] if row["evidence_id"] not in removed]
            package["evidence_refs"][-1]["source_stage"] = "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE"
            for binding in package["trace_bindings"]:
                binding["evidence_ids"] = [eid for eid in binding["evidence_ids"] if eid not in removed]
        run = validate_package(self._mutated("c2-fat-sat", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T011"].result)

    def test_effectiveness_metrics_are_evidence_sourced(self):
        for name in ("c0-supplier", "c1-lab", "c2-fat-sat", "c3-continuous"):
            with self.subTest(name=name):
                package = json.loads((ROOT / "examples" / name / "package.json").read_text(encoding="utf-8"))
                evidence_ids = {row["evidence_id"] for row in package["evidence_refs"]}
                for metric_name, source in package["effectiveness_sources"].items():
                    refs = source.get("source_evidence_ids")
                    self.assertIsInstance(refs, list, metric_name)
                    self.assertTrue(refs, metric_name)
                    self.assertTrue(set(refs).issubset(evidence_ids), metric_name)
                run = validate_package(ROOT / "examples" / name)
                for metric_name, metric in run.metrics.items():
                    self.assertIn("source_evidence_ids", metric, metric_name)
                    self.assertTrue(metric["source_evidence_ids"], metric_name)

    def test_machine_schema_is_closed_and_types_core_nested_objects(self):
        schema = json.loads((REPO / "machine-readable" / "p0-08" / "conformity-assessment-v1.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        defs = schema["$defs"]
        for name in (
            "assessment_object", "baseline", "assurance_entry", "execution_summary",
            "required_outcome", "metric_source", "metric_value", "validity",
            "drift", "trace_binding", "evidence_ref"
        ):
            self.assertIn(name, defs)
        expected_refs = {
            "assessment_object": "#/$defs/assessment_object",
            "baseline": "#/$defs/baseline",
            "observed_baseline": "#/$defs/baseline",
            "execution_summary": "#/$defs/execution_summary",
            "validity": "#/$defs/validity",
        }
        for field, ref in expected_refs.items():
            self.assertEqual(ref, schema["properties"][field].get("$ref"), field)


if __name__ == "__main__":
    unittest.main()
