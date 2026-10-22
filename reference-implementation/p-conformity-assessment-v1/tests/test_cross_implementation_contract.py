from __future__ import annotations

import copy
import hashlib
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

    def test_node_rejects_coordinated_upstream_hash_forgery(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "package"
            shutil.copytree(ROOT / "examples" / "c2-fat-sat", target)
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
            completed, payload = self._verify(target)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(payload.get("valid", True))
            self.assertFalse(payload.get("baseline_bindings_valid", True))

    def _mutated_package(self, name: str, mutate) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory()
        target = Path(td.name) / "package"
        shutil.copytree(ROOT / "examples" / name, target)
        package_path = target / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        mutate(package, target)
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return td, target

    @staticmethod
    def _rewrite_proof(package: dict, target: Path, evidence_id: str, mutate) -> None:
        ref = next(row for row in package["evidence_refs"] if row["evidence_id"] == evidence_id)
        proof_path = target / ref["uri"]
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        replacement = mutate(proof)
        proof = proof if replacement is None else replacement
        data = json.dumps(proof, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        proof_path.write_bytes(data)
        ref["size_bytes"] = len(data)
        ref["sha256"] = hashlib.sha256(data).hexdigest()

    def test_node_rejects_semantically_invalid_c0_proofs(self):
        cases = (
            ("EV-MODEL", lambda proof: {}),
            ("EV-PROFILE", lambda proof: {**proof, "profile_id": "UNRELATED-PROFILE"}),
            ("EV-VALIDATOR", lambda proof: {**proof, "result": "FAIL"}),
        )
        for evidence_id, proof_mutate in cases:
            with self.subTest(evidence_id=evidence_id):
                td, target = self._mutated_package(
                    "c0-supplier",
                    lambda package, root: self._rewrite_proof(package, root, evidence_id, proof_mutate),
                )
                self.addCleanup(td.cleanup)
                completed, payload = self._verify(target)
                self.assertNotEqual(0, completed.returncode)
                self.assertFalse(payload.get("valid", True))
                self.assertFalse(payload.get("proof_semantics_valid", True))

    def test_node_rejects_unknown_or_incomplete_required_outcomes(self):
        def mutate(package, _target):
            package["required_outcomes"] = [{"requirement_id": "UNKNOWN-R999", "result": "NOT_APPLICABLE"}]
            package["not_applicable"] = []
            package["declared_decision"] = "PASS"
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))
        self.assertFalse(payload.get("outcomes_valid", True))

    def test_node_rejects_zero_day_c3_monitoring_window(self):
        def mutate(package, _target):
            package["continuous_monitoring"]["required_days"] = 0
            package["continuous_monitoring"]["window_end"] = package["continuous_monitoring"]["window_start"]
        td, target = self._mutated_package("c3-continuous", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))

    def test_node_open_material_drift_in_continuous_evidence_requires_reevaluation(self):
        def mutate(package, target):
            self._rewrite_proof(
                package,
                target,
                "EV-CONTINUOUS",
                lambda proof: {**proof, "material_open_drifts": 1},
            )
            for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                metric = package[section]["c3_drift_closure_rate"]
                metric["numerator"], metric["denominator"] = 1, 2
            package["claimed_effectiveness_metrics"]["c3_drift_closure_rate"]["value"] = 0.5
        td, target = self._mutated_package("c3-continuous", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("REEVALUATION_REQUIRED", payload.get("lifecycle_state"))
        self.assertFalse(payload.get("drift_declaration_valid", True))

    def test_node_rejects_failing_direct_automated_proof_at_c1(self):
        def mutate(package, target):
            self._rewrite_proof(package, target, "EV-VALIDATOR", lambda proof: {**proof, "result": "FAIL"})
            for metric_name in ("requirement_testability", "automation_rate", "applicable_required_pass_rate"):
                for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                    package[section][metric_name]["source_evidence_ids"] = ["EV-P0-02-STATUS"]
        td, target = self._mutated_package("c1-lab", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("proof_semantics_valid", True))
        self.assertFalse(payload.get("outcomes_valid", True))

    def test_node_direct_proofs_are_bound_to_object_and_baseline(self):
        def mutate(package, _target):
            package["assessment_object"]["object_id"] = "urn:example:assessment-object:unrelated"
            package["statement_scope"]["assessment_object_id"] = package["assessment_object"]["object_id"]
            package["baseline"]["parameter_hash"] = "0" * 64
            package["observed_baseline"]["parameter_hash"] = "0" * 64
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("proof_semantics_valid", True))

    def test_node_trace_enforces_all_cac_evidence_requirements_for_c2(self):
        def mutate(package, _target):
            binding = next(row for row in package["trace_bindings"] if row["test_id"] == "CAE-T011")
            binding["evidence_ids"] = ["EV-FAT-SAT"]
        td, target = self._mutated_package("c2-fat-sat", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("trace_valid", True))

    def test_node_rejects_wrong_profile_and_expired_current_assessment(self):
        cases = (
            lambda package, _target: package["profile"].update({"id": "UNRELATED-PROFILE"}),
            lambda package, _target: package["validity"].update({"valid_until": "2026-07-01T00:00:00Z"}),
        )
        for mutate in cases:
            td, target = self._mutated_package("c0-supplier", mutate)
            self.addCleanup(td.cleanup)
            completed, payload = self._verify(target)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(payload.get("valid", True))

    def test_node_rejects_signed_verified_without_signature(self):
        def mutate(package, _target):
            package["signature_state"] = "SIGNED_VERIFIED"
            package.pop("signature", None)
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))

    def test_node_rejects_symlinked_evidence_escape(self):
        td, target = self._mutated_package("c0-supplier", lambda package, root: None)
        self.addCleanup(td.cleanup)
        outside = target.parent / "outside-model.json"
        model = target / "proof" / "model.json"
        outside.write_bytes(model.read_bytes())
        model.unlink()
        model.symlink_to(outside)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))
        self.assertFalse(payload.get("evidence_hashes_valid", True))

    def test_node_rejects_coordinately_forged_effectiveness_counters(self):
        def mutate(package, _target):
            for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                package[section]["machine_readable_coverage"]["numerator"] = 999
                package[section]["machine_readable_coverage"]["denominator"] = 999
        td, target = self._mutated_package("c1-lab", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("metrics_valid", True))

    def test_node_derives_upstream_metrics_from_the_frozen_status_content(self):
        def mutate(package, target):
            self._rewrite_proof(
                package,
                target,
                "EV-P0-02-STATUS",
                lambda proof: {**proof, "verified_implementations": 999, "total_implementations": 999},
            )
            for section in ("effectiveness_sources", "claimed_effectiveness_metrics"):
                package[section]["cross_implementation_reproducibility"]["numerator"] = 999
                package[section]["cross_implementation_reproducibility"]["denominator"] = 999
        td, target = self._mutated_package("c1-lab", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("baseline_bindings_valid", True))
        self.assertFalse(payload.get("metrics_valid", True))

    def test_node_rejects_irrelevant_single_source_trace(self):
        def mutate(package, _target):
            for binding in package["trace_bindings"]:
                binding["evidence_ids"] = ["EV-P0-02-STATUS"]
        td, target = self._mutated_package("c1-lab", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("trace_valid", True))

    def test_node_enforces_published_package_schema_at_runtime(self):
        def mutate(package, _target):
            package["unexpected_fail_open_field"] = True
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("schema_valid", True))

    def test_node_malformed_schema_shape_fails_closed_with_json_result(self):
        def mutate(package, _target):
            package["evidence_refs"] = "not-an-array"
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("valid", True))
        self.assertFalse(payload.get("schema_valid", True))

    def test_node_rejects_predecessor_attestation_replay_for_another_object(self):
        def mutate(package, _target):
            package["assessment_object"]["object_id"] = "urn:example:assessment-object:unrelated"
        td, target = self._mutated_package("c1-lab", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("predecessor_rules_valid", True))

    def test_node_rejects_wrong_criteria_registry_snapshot(self):
        def mutate(package, _target):
            package["criteria_registry"] = {
                "registry_id": "P-CAE-AUTO-R14-CAC",
                "registry_version": "1.0",
                "sha256": "0" * 64,
            }
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("registry_valid", True))

    def test_node_rejects_wrong_evidence_media_type(self):
        def mutate(package, _target):
            package["evidence_refs"][0]["media_type"] = "text/plain"
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("evidence_hashes_valid", True))

    def test_node_rejects_mismatched_conformity_statement_scope(self):
        def mutate(package, _target):
            package["statement_scope"] = {
                "assessment_object_id": "urn:example:assessment-object:unrelated",
                "assessment_level": package["assessment_level"],
                "profile_id": package["profile"]["id"],
                "profile_version": package["profile"]["version"],
            }
        td, target = self._mutated_package("c0-supplier", mutate)
        self.addCleanup(td.cleanup)
        completed, payload = self._verify(target)
        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(payload.get("statement_valid", True))


if __name__ == "__main__":
    unittest.main()
