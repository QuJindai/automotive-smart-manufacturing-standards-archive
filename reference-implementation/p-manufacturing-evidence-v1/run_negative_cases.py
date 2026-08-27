#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pme.canonical import record_sha256
from pme.validator import validate_package

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "fixtures" / "negative-cases.json"
BASE = ROOT / "examples" / "eol-rework-retest"


def _rehash_chain(package: dict[str, Any]) -> None:
    by_id: dict[str, dict[str, Any]] = {}
    for record in package["records"]:
        parents = record["lineage"].get("parent_evidence_ids") or []
        if parents and parents[0] in by_id:
            record["lineage"]["previous_record_hash"] = by_id[parents[0]]["integrity"]["record_sha256"]
        elif not parents:
            record["lineage"]["previous_record_hash"] = None
        record["integrity"]["record_sha256"] = record_sha256(record)
        by_id.setdefault(record["evidence_id"], record)


def _mutate(package: dict[str, Any], name: str) -> None:
    records = package["records"]
    if name == "duplicate_id":
        records[-1]["evidence_id"] = records[0]["evidence_id"]
    elif name == "remove_source_system":
        records[0]["source"].pop("system_id", None)
    elif name == "mismatch_equipment":
        records[0]["process_context"]["equipment_id"] = "urn:example:synthetic:equipment:mismatch"
    elif name == "wrong_program_version":
        records[0]["execution_context"]["program_version"] = "9.9.9"
    elif name == "wrong_parameter_hash":
        records[0]["execution_context"]["parameter_hash"] = "0" * 64
    elif name == "timestamp_inversion":
        records[2]["time"]["event_time"] = "2026-08-26T23:59:59Z"
        records[2]["time"]["collected_time"] = "2026-08-27T00:00:08Z"
    elif name == "record_tamper":
        records[0]["measurement"]["raw_value"] = 99.0
        return
    elif name == "unknown_parent":
        records[2]["lineage"]["parent_evidence_ids"] = ["ME-UNKNOWN"]
        records[2]["lineage"]["previous_record_hash"] = "0" * 64
        records[2]["integrity"]["record_sha256"] = record_sha256(records[2])
        return
    elif name == "wrong_previous_hash":
        records[2]["lineage"]["previous_record_hash"] = "0" * 64
        records[2]["integrity"]["record_sha256"] = record_sha256(records[2])
        return
    elif name == "attempt_gap":
        records[2]["lineage"]["attempt_no"] = 3
        records[3]["lineage"]["attempt_no"] = 3
    elif name == "illegal_retest":
        records[2]["disposition"]["decision"] = "REWORK"
    elif name == "illegal_release":
        records[3]["lineage"]["parent_evidence_ids"] = [records[1]["evidence_id"]]
    elif name in {"missing_artifact", "tamper_artifact"}:
        return
    else:
        raise ValueError(f"unknown mutation: {name}")
    _rehash_chain(package)


def execute_case(case: dict[str, Any], work_root: Path) -> dict[str, Any]:
    case_root = work_root / case["case_id"]
    shutil.copytree(BASE, case_root)
    package_path = case_root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package = copy.deepcopy(package)
    _mutate(package, case["mutation"])
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

    first_uri = package["records"][0]["raw_artifacts"][0]["uri"]
    if case["mutation"] == "missing_artifact":
        (case_root / first_uri).unlink()
    elif case["mutation"] == "tamper_artifact":
        (case_root / first_uri).write_bytes(b'{"tampered":true}')

    run = validate_package(case_root)
    results = {row.test_id: row for row in run.results}
    intended = results[case["intended_test"]]
    failed_tests = [row.test_id for row in run.results if row.result in {"FAIL", "BLOCKED"}]
    return {
        "case_id": case["case_id"],
        "mutation": case["mutation"],
        "intended_test": case["intended_test"],
        "observed_result": intended.result,
        "observed_reason": intended.reason,
        "failed_tests": failed_tests,
        "false_pass": intended.result == "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute P-ME V1 negative/tamper cases")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="pme-negative-") as td:
        rows = [execute_case(case, Path(td)) for case in registry["cases"]]

    false_passes = [row for row in rows if row["false_pass"]]
    summary = {
        "schema_version": "1.0",
        "profile_id": "P-ME-EOL",
        "profile_version": "1.0",
        "case_count": len(rows),
        "false_pass_count": len(false_passes),
        "cases": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"ME_NEGATIVE_CASES={len(rows)}")
    print(f"ME_NEGATIVE_FALSE_PASSES={len(false_passes)}")
    return 1 if false_passes else 0


if __name__ == "__main__":
    raise SystemExit(main())
