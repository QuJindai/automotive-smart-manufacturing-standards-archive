#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pcae.evaluator import validate_package

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "fixtures" / "negative-cases.json"
EXAMPLES = ROOT / "examples"


def _mutate(package: dict[str, Any], mutation: str) -> None:
    if mutation == "proof_sha_mismatch":
        package["evidence_refs"][0]["sha256"] = "0" * 64
    elif mutation == "invalid_assessor_role":
        package["assessor"]["role"] = "SUPPLIER_DECLARANT"
    elif mutation == "manual_pass_automatable":
        package["execution_summary"]["manual_passed_automatable"] = 1
        package["execution_summary"]["automated_executed"] = package["execution_summary"]["automatable_required"] - 1
    elif mutation == "illegal_not_applicable":
        package["not_applicable"] = [{"test_id": "CAE-T010", "permitted": False, "justification": ""}]
    elif mutation == "exception_masks_failure":
        package["exceptions"] = [{"exception_id": "EXC-001", "masks_required_failure": True, "reason": "synthetic invalid exception"}]
    elif mutation == "remove_c0_predecessor":
        package["assurance_chain"] = [row for row in package.get("assurance_chain", []) if row.get("level") != "C0"]
    elif mutation == "remove_c1_predecessor":
        package["assurance_chain"] = [row for row in package.get("assurance_chain", []) if row.get("level") != "C1"]
    elif mutation == "remove_project_binding":
        package.pop("project_binding", None)
    elif mutation == "remove_p0_06_proof":
        removed = {row.get("evidence_id") for row in package.get("evidence_refs", []) if row.get("source_stage") == "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE"}
        package["evidence_refs"] = [row for row in package.get("evidence_refs", []) if row.get("evidence_id") not in removed]
    elif mutation == "insufficient_c3_coverage":
        package["continuous_monitoring"]["coverage_ratio"] = 0.8
    elif mutation == "truthful_material_drift":
        package["observed_baseline"]["parameter_hash"] = "0" * 64
        package["declared_material_drift"] = True
        package["claimed_reevaluation_state"] = "REQUIRED"
        package["drifts"] = [{"drift_id": "DRIFT-MATERIAL-001", "material": True, "status": "OPEN", "description": "synthetic parameter baseline change"}]
    elif mutation == "undeclared_material_drift":
        package["observed_baseline"]["parameter_hash"] = "0" * 64
        package["declared_material_drift"] = False
        package["claimed_reevaluation_state"] = "NOT_REQUIRED"
    elif mutation == "expired_assessment":
        package["validity"]["valid_until"] = "2026-07-31T00:00:00Z"
        package["claimed_reevaluation_state"] = "REQUIRED"
    elif mutation == "revoked_c1_predecessor":
        for row in package.get("assurance_chain", []):
            if row.get("level") == "C1":
                row["lifecycle_state"] = "REVOKED"
    elif mutation == "upstream_blob_mismatch":
        package["baseline"]["p0_06_status_blob_sha"] = "0" * 40
    elif mutation == "tampered_effectiveness_metric":
        package["claimed_effectiveness_metrics"]["automation_rate"]["value"] = 0.5
    elif mutation == "fake_certification_claim":
        package["certification_claim"] = True
        package["statement_type"] = "CERTIFICATE"
    elif mutation == "missing_proof_file":
        return
    else:
        raise ValueError(f"unknown mutation: {mutation}")


def execute_case(case: dict[str, Any], work_root: Path) -> dict[str, Any]:
    case_root = work_root / case["case_id"]
    shutil.copytree(EXAMPLES / case["base"], case_root)
    package_path = case_root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    _mutate(package, case["mutation"])
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    if case["mutation"] == "missing_proof_file":
        target = case_root / package["evidence_refs"][0]["uri"]
        target.unlink()

    run = validate_package(case_root)
    by_id = {row.test_id: row for row in run.results}
    intended = by_id[case["intended_test"]]
    expected_result = case["expected_result"]
    expected_lifecycle = case.get("expected_lifecycle_state")
    result_mismatch = intended.result != expected_result
    lifecycle_mismatch = expected_lifecycle is not None and run.lifecycle_state != expected_lifecycle
    return {
        "case_id": case["case_id"],
        "base": case["base"],
        "mutation": case["mutation"],
        "intended_test": case["intended_test"],
        "expected_result": expected_result,
        "observed_result": intended.result,
        "observed_reason": intended.reason,
        "expected_lifecycle_state": expected_lifecycle,
        "observed_lifecycle_state": run.lifecycle_state,
        "overall_decision": run.overall_decision,
        "failed_tests": [row.test_id for row in run.results if row.result in {"FAIL", "BLOCKED"}],
        "false_pass": result_mismatch or lifecycle_mismatch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute P-CAE V1 negative and lifecycle cases")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="pcae-negative-") as td:
        rows = [execute_case(case, Path(td)) for case in registry["cases"]]

    false_passes = [row for row in rows if row["false_pass"]]
    summary = {
        "schema_version": "1.0",
        "profile_id": "P-CAE-AUTO-R14",
        "profile_version": "1.0",
        "case_count": len(rows),
        "false_pass_count": len(false_passes),
        "cases": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"CAE_NEGATIVE_CASES={len(rows)}")
    print(f"CAE_NEGATIVE_FALSE_PASSES={len(false_passes)}")
    return 1 if false_passes else 0


if __name__ == "__main__":
    raise SystemExit(main())
