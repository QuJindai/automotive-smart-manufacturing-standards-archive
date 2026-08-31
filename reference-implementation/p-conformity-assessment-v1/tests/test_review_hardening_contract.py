from __future__ import annotations

import json
import hashlib
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

    def _forged_upstream_package(self) -> Path:
        target = self._mutated("c2-fat-sat", lambda package: None)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        forged = {"P0-02": "1" * 40, "P0-06": "2" * 40}
        baseline_fields = {"P0-02": "p0_02_status_blob_sha", "P0-06": "p0_06_status_blob_sha"}
        for standard_id, forged_blob_sha in forged.items():
            field = baseline_fields[standard_id]
            package["baseline"][field] = forged_blob_sha
            package["observed_baseline"][field] = forged_blob_sha
            ref = next(
                row for row in package["evidence_refs"]
                if row.get("source_stage", "").startswith(f"R14_{standard_id.replace('-', '_')}")
            )
            proof_path = target / ref["uri"]
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            proof["source_blob_sha"] = forged_blob_sha
            data = json.dumps(proof, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            proof_path.write_bytes(data)
            ref["size_bytes"] = len(data)
            ref["sha256"] = hashlib.sha256(data).hexdigest()
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def _mutated_proof(self, name: str, evidence_id: str, mutate) -> Path:
        target = self._mutated(name, lambda package: None)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        ref = next(row for row in package["evidence_refs"] if row["evidence_id"] == evidence_id)
        proof_path = target / ref["uri"]
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        replacement = mutate(proof)
        proof = proof if replacement is None else replacement
        data = json.dumps(proof, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        proof_path.write_bytes(data)
        ref["size_bytes"] = len(data)
        ref["sha256"] = hashlib.sha256(data).hexdigest()
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

    def test_coordinated_upstream_hash_forgery_cannot_replace_profile_trust_anchors(self):
        run = validate_package(self._forged_upstream_package())
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T013"].result)
        self.assertEqual("FAIL", run.overall_decision)

    def test_c0_proof_contents_must_be_semantically_valid(self):
        cases = (
            ("EV-MODEL", lambda proof: {}),
            ("EV-PROFILE", lambda proof: {**proof, "profile_id": "UNRELATED-PROFILE"}),
            ("EV-VALIDATOR", lambda proof: {**proof, "result": "FAIL"}),
        )
        for evidence_id, mutate in cases:
            with self.subTest(evidence_id=evidence_id):
                run = validate_package(self._mutated_proof("c0-supplier", evidence_id, mutate))
                by_id = {row.test_id: row for row in run.results}
                self.assertEqual("FAIL", by_id["CAE-T009"].result)
                self.assertEqual("FAIL", run.overall_decision)

    def test_required_outcomes_must_match_complete_authoritative_registry(self):
        def mutate(package):
            package["required_outcomes"] = [{"requirement_id": "UNKNOWN-R999", "result": "NOT_APPLICABLE"}]
            package["not_applicable"] = []
            package["declared_decision"] = "PASS"
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T007"].result)
        self.assertEqual("FAIL", by_id["CAE-T017"].result)

    def test_zero_day_c3_monitoring_window_is_invalid(self):
        def mutate(package):
            package["continuous_monitoring"]["required_days"] = 0
            package["continuous_monitoring"]["window_end"] = package["continuous_monitoring"]["window_start"]
        run = validate_package(self._mutated("c3-continuous", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T012"].result)

    def test_open_material_drift_in_continuous_evidence_triggers_reevaluation(self):
        target = self._mutated("c3-continuous", lambda package: None)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        ref = next(row for row in package["evidence_refs"] if row["evidence_id"] == "EV-CONTINUOUS")
        proof_path = target / ref["uri"]
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["material_open_drifts"] = 1
        data = json.dumps(proof, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        proof_path.write_bytes(data)
        ref["size_bytes"] = len(data)
        ref["sha256"] = hashlib.sha256(data).hexdigest()
        for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
            metric = package[section]["c3_drift_closure_rate"]
            metric["numerator"], metric["denominator"] = 1, 2
        package["claimed_effectiveness_metrics"]["c3_drift_closure_rate"]["value"] = 0.5
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        run = validate_package(target)
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T014"].result)
        self.assertEqual("REEVALUATION_REQUIRED", run.lifecycle_state)

    def test_failing_direct_automated_proof_cannot_be_ignored_at_c1(self):
        target = self._mutated_proof("c1-lab", "EV-VALIDATOR", lambda proof: {**proof, "result": "FAIL"})
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        for metric_name in ("requirement_testability", "automation_rate", "applicable_required_pass_rate"):
            for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                package[section][metric_name]["source_evidence_ids"] = ["EV-P0-02-STATUS"]
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        run = validate_package(target)
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T004"].result)
        self.assertEqual("FAIL", by_id["CAE-T017"].result)

    def test_direct_proofs_are_bound_to_assessed_object_and_baseline(self):
        def mutate(package):
            package["assessment_object"]["object_id"] = "urn:example:assessment-object:unrelated"
            package["statement_scope"]["assessment_object_id"] = package["assessment_object"]["object_id"]
            package["baseline"]["parameter_hash"] = "0" * 64
            package["observed_baseline"]["parameter_hash"] = "0" * 64
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T009"].result)

    def test_trace_enforces_all_cac_evidence_requirements_for_c2(self):
        def mutate(package):
            binding = next(row for row in package["trace_bindings"] if row["test_id"] == "CAE-T011")
            binding["evidence_ids"] = ["EV-FAT-SAT"]
        run = validate_package(self._mutated("c2-fat-sat", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T019"].result)

    def test_signed_verified_without_signature_is_rejected(self):
        def mutate(package):
            package["signature_state"] = "SIGNED_VERIFIED"
            package.pop("signature", None)
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T020"].result)

    def test_symlinked_evidence_cannot_escape_package_root(self):
        target = self._mutated("c0-supplier", lambda package: None)
        outside = target.parent / "outside-model.json"
        model = target / "proof" / "model.json"
        outside.write_bytes(model.read_bytes())
        model.unlink()
        model.symlink_to(outside)
        run = validate_package(target)
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T003"].result)

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

    def test_effectiveness_metric_counters_cannot_be_coordinately_forged(self):
        def mutate(package):
            for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                package[section]["machine_readable_coverage"]["numerator"] = 999
                package[section]["machine_readable_coverage"]["denominator"] = 999
        run = validate_package(self._mutated("c1-lab", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T018"].result)

    def test_upstream_summary_and_derived_metrics_use_the_frozen_status_content(self):
        target = self._mutated("c1-lab", lambda package: None)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        ref = next(row for row in package["evidence_refs"] if row["evidence_id"] == "EV-P0-02-STATUS")
        proof_path = target / ref["uri"]
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["verified_implementations"] = 999
        proof["total_implementations"] = 999
        data = json.dumps(proof, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        proof_path.write_bytes(data)
        ref["size_bytes"] = len(data)
        ref["sha256"] = hashlib.sha256(data).hexdigest()
        for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
            package[section]["cross_implementation_reproducibility"]["numerator"] = 999
            package[section]["cross_implementation_reproducibility"]["denominator"] = 999
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        run = validate_package(target)
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T013"].result)
        self.assertEqual("FAIL", by_id["CAE-T018"].result)

    def test_trace_bindings_require_semantically_relevant_direct_evidence(self):
        def mutate(package):
            for binding in package["trace_bindings"]:
                binding["evidence_ids"] = ["EV-P0-02-STATUS"]
        run = validate_package(self._mutated("c1-lab", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T019"].result)

    def test_runtime_enforces_published_package_schema(self):
        def mutate(package):
            package["unexpected_fail_open_field"] = True
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T001"].result)

    def test_malformed_schema_shape_fails_closed_without_exception(self):
        def mutate(package):
            package["evidence_refs"] = "not-an-array"
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T001"].result)
        self.assertEqual("FAIL", run.overall_decision)

    def test_predecessor_attestation_cannot_be_replayed_for_another_object(self):
        def mutate(package):
            package["assessment_object"]["object_id"] = "urn:example:assessment-object:unrelated"
        run = validate_package(self._mutated("c1-lab", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T010"].result)

    def test_package_binds_the_authoritative_criteria_registry_snapshot(self):
        def mutate(package):
            package["criteria_registry"] = {
                "registry_id": "P-CAE-AUTO-R14-CAC",
                "registry_version": "1.0",
                "sha256": "0" * 64,
            }
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T002"].result)

    def test_evidence_media_type_must_match_the_json_proof_parser(self):
        def mutate(package):
            package["evidence_refs"][0]["media_type"] = "text/plain"
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T003"].result)

    def test_conformity_statement_scope_must_match_assessment_identity(self):
        def mutate(package):
            package["statement_scope"] = {
                "assessment_object_id": "urn:example:assessment-object:unrelated",
                "assessment_level": package["assessment_level"],
                "profile_id": package["profile"]["id"],
                "profile_version": package["profile"]["version"],
            }
        run = validate_package(self._mutated("c0-supplier", mutate))
        by_id = {row.test_id: row for row in run.results}
        self.assertEqual("FAIL", by_id["CAE-T020"].result)

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
        self.assertIn("criteria_registry", schema["required"])
        self.assertIn("statement_scope", schema["required"])
        self.assertIn("media_type", defs["evidence_ref"]["required"])


if __name__ == "__main__":
    unittest.main()
