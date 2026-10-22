from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .evaluator import AssessmentRun


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_outputs(run: AssessmentRun, out_dir: Path) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    package = run.package
    level = package.get("assessment_level") or "C0"
    assessment_time = package.get("assessment_time") or "1970-01-01T00:00:00Z"

    values = {
        "assessment-summary.json": {
            "schema_version": "1.0",
            "assessment_id": package.get("assessment_id"),
            "assessment_level": level,
            "counts": run.counts,
            "required_failures": run.required_failures,
            "overall_decision": run.overall_decision,
            "lifecycle_state": run.lifecycle_state,
            "certification_claim": False,
        },
        "criteria-results.json": {
            "schema_version": "1.0",
            "assessment_id": package.get("assessment_id"),
            "results": [row.to_dict() for row in run.results],
        },
        "effectiveness-metrics.json": {
            "schema_version": "1.0",
            "assessment_id": package.get("assessment_id"),
            "weighted_score": None,
            "metrics": run.metrics,
        },
        "evidence-trace.json": run.evidence_trace,
        "reevaluation-state.json": run.reevaluation,
        "conformity-statement.json": {
            "schema_version": "1.0",
            "statement_type": "CONFORMITY_EVALUATION_STATEMENT",
            "assessment_id": package.get("assessment_id"),
            "assessment_level": level,
            "decision": run.overall_decision,
            "lifecycle_state": run.lifecycle_state,
            "validity": package.get("validity"),
            "scope": package.get("statement_scope"),
            "signature_state": package.get("signature_state", "UNSIGNED"),
            "certification_claim": False,
        },
    }
    for name, value in values.items():
        _write(out_dir / name, value)

    artifact_refs = []
    for name in sorted(values):
        path = out_dir / name
        artifact_refs.append({
            "artifact_id": "ART-P-CAE-" + name.upper().replace(".", "-"),
            "name": name,
            "uri": name,
            "sha256": _sha256(path),
            "mime_type": "application/json",
            "created_at": assessment_time,
            "source_system": "p-conformity-assessment-v1",
        })

    validator_evidence = {
        "schema_version": "1.0",
        "evidence_bundle_id": "EVB-P-CAE-" + str(package.get("assessment_id", "unknown")).split(":")[-1],
        "profile_version": "P-CAE-AUTO-R14-1.0",
        "system_under_test": {
            "name": "P-CAE automotive assessment package",
            "version": "1.0",
            "site": "public-ci-synthetic",
            "asset_ids": [str((package.get("assessment_object") or {}).get("object_id", "synthetic"))],
            "model_ids": [],
        },
        "run_started_at": assessment_time,
        "run_completed_at": assessment_time,
        "environment": {
            "validator": "python-reference",
            "assessment_level": level,
            "lifecycle_state": run.lifecycle_state,
            "overall_decision": run.overall_decision,
            "certification_claim": False,
            "output_artifacts": artifact_refs,
        },
        "test_results": [
            {
                "test_id": row.test_id,
                "level": level,
                "result": row.result,
                "executed_at": assessment_time,
                "executor": "p-conformity-assessment-v1",
                "linked_rule_ids": [row.test_id.replace("CAE-T", "CAE-R")],
                "metrics": {},
                "observations": row.reason,
                "assertions": [{
                    "assertion_id": row.test_id + "-assertion",
                    "status": row.result,
                    "expected": "P-CAE requirement satisfied",
                    "observed": row.observations,
                    "message": row.reason,
                }],
                "artifacts": [],
                "deviations": [],
            }
            for row in run.results
        ],
        "bundle_sha256": None,
        "signatures": [],
    }
    _write(out_dir / "validator-evidence.json", validator_evidence)
    return {name: str(out_dir / name) for name in [*values, "validator-evidence.json"]}
