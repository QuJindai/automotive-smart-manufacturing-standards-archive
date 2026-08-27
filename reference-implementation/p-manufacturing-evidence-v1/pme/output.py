from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import file_sha256, package_sha256
from .validator import ValidationRun


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_outputs(run: ValidationRun, out_dir: Path) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = run.counts

    conformance = {"schema_version": "1.0", "profile_id": "P-ME-EOL", "profile_version": "1.0", "results": [r.to_dict() for r in run.results]}
    summary = {"schema_version": "1.0", "package_id": run.package.get("package_id"), "profile": run.package.get("profile"), "counts": counts, "required_failures": run.required_failures, "certification_claim": False}
    manifest = {"schema_version": "1.0", "package_id": run.package.get("package_id"), "package_sha256": package_sha256(run.package), "records": [{"evidence_id": r.get("evidence_id"), "record_sha256": (r.get("integrity") or {}).get("record_sha256"), "raw_artifacts": r.get("raw_artifacts") or []} for r in run.package.get("records") or []]}

    paths = {"validation-summary.json": summary, "conformance-results.json": conformance, "trace-graph.json": run.trace_graph, "trace-query-release.json": run.trace_query, "evidence-package-manifest.json": manifest}
    for name, value in paths.items():
        _write(out_dir / name, value)

    artifact_refs = []
    for name in sorted(paths):
        path = out_dir / name
        artifact_refs.append({"artifact_id": "ART-P-ME-" + name.upper().replace(".", "-"), "name": name, "uri": name, "sha256": file_sha256(path), "mime_type": "application/json", "created_at": _now(), "source_system": "p-manufacturing-evidence-v1"})

    now = _now()
    validator_evidence = {
        "schema_version": "1.0",
        "evidence_bundle_id": "EVB-P-ME-V1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "profile_version": "P-ME-EOL-1.0",
        "system_under_test": {"name": "P-ME synthetic EOL evidence package", "version": "1.0", "site": "public-ci-synthetic", "asset_ids": ["urn:example:automotive:asset:eol-station-001"], "model_ids": []},
        "run_started_at": now,
        "run_completed_at": now,
        "environment": {"validator": "python-reference", "schema": "P-ME-V1", "test_kit": "P-ME-EOL-TCK-1.0", "input_package_sha256": package_sha256(run.package), "certification_claim": False, "output_artifacts": artifact_refs},
        "test_results": [{"test_id": r.test_id, "level": "C1", "result": r.result, "executed_at": now, "executor": "p-manufacturing-evidence-v1", "linked_rule_ids": [r.test_id], "metrics": {}, "observations": r.reason, "assertions": [{"assertion_id": r.test_id + "-assertion", "status": r.result, "expected": "P-ME V1 conformance requirement satisfied", "observed": r.observations, "message": r.reason}], "artifacts": [], "deviations": []} for r in run.results],
        "bundle_sha256": None,
        "signatures": [],
    }
    _write(out_dir / "validator-evidence.json", validator_evidence)
    return {name: str(out_dir / name) for name in [*paths, "validator-evidence.json"]}
