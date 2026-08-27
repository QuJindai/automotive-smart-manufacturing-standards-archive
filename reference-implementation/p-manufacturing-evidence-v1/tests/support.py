from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


EQUIPMENT_ID = "urn:example:automotive:asset:eol-station-001"
SUBJECT_ID = "urn:example:synthetic:vehicle:eol-0001"
OPERATION_ID = "EOL-ELECTRICAL-CHECK"
PROGRAM_ID = "EOL_REFERENCE"
PROGRAM_VERSION = "1.0.0"
PARAMETER_SET_ID = "EOL-PARAM-001"
PARAMETER_HASH = hashlib.sha256(b"synthetic-eol-parameter-set-v1").hexdigest()


def canonical_record_bytes(record: dict) -> bytes:
    candidate = copy.deepcopy(record)
    integrity = dict(candidate.get("integrity") or {})
    integrity.pop("record_sha256", None)
    candidate["integrity"] = integrity
    return json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def record_hash(record: dict) -> str:
    return hashlib.sha256(canonical_record_bytes(record)).hexdigest()


def _raw_payload(kind: str, attempt: int, decision: str) -> bytes:
    return json.dumps(
        {"synthetic": True, "kind": kind, "attempt": attempt, "decision": decision},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def make_record(evidence_id: str, *, attempt: int, relation: str, decision: str, parent: dict | None = None, second: int = 0) -> tuple[dict, bytes]:
    payload = _raw_payload(relation, attempt, decision)
    raw_uri = f"raw/{evidence_id}.json"
    raw_hash = hashlib.sha256(payload).hexdigest()
    parent_ids = [parent["evidence_id"]] if parent else []
    previous_hash = parent["integrity"]["record_sha256"] if parent else None
    record = {
        "evidence_id": evidence_id,
        "schema_version": "1.0",
        "profile_id": "P-ME-EOL",
        "profile_version": "1.0",
        "subject": {"subject_id": SUBJECT_ID, "subject_type": "VEHICLE", "operation_id": OPERATION_ID},
        "source": {"system_id": "urn:example:synthetic:eol-tester", "equipment_id": EQUIPMENT_ID, "source_record_id": f"SRC-{evidence_id}"},
        "process_context": {"process_id": "EOL", "station_id": "EOL-001", "equipment_id": EQUIPMENT_ID},
        "measurement": {
            "characteristic_id": "battery-voltage" if relation != "RELEASES" else "release-decision",
            "raw_value": 13.72 if relation != "RELEASES" else "PASS",
            "result_value": 13.72 if relation != "RELEASES" else "RELEASED",
            "unit": "V" if relation != "RELEASES" else "1",
            "judgment": "PASS" if decision in {"PASS", "RELEASED"} else "FAIL",
            "uncertainty": {"value": 0.05, "unit": "V", "method": "synthetic-reference"} if relation != "RELEASES" else {"not_applicable_reason": "decision-only evidence"},
        },
        "execution_context": {
            "program_id": PROGRAM_ID,
            "program_version": PROGRAM_VERSION,
            "parameter_set_id": PARAMETER_SET_ID,
            "parameter_hash": PARAMETER_HASH,
            "tool_state": "READY",
        },
        "time": {"event_time": f"2026-08-27T00:00:{second:02d}Z", "collected_time": f"2026-08-27T00:00:{second + 1:02d}Z"},
        "lineage": {"attempt_no": attempt, "relation": relation, "parent_evidence_ids": parent_ids, "previous_record_hash": previous_hash},
        "raw_artifacts": [{"artifact_id": f"RAW-{evidence_id}", "uri": raw_uri, "mime_type": "application/json", "size_bytes": len(payload), "sha256": raw_hash}],
        "disposition": {"decision": decision, "rule_id": "EOL-RULE-REFERENCE"},
        "integrity": {"record_sha256": ""},
    }
    record["integrity"]["record_sha256"] = record_hash(record)
    return record, payload


def valid_rework_package() -> tuple[dict, dict[str, bytes]]:
    r1, p1 = make_record("ME-EOL-001", attempt=1, relation="INITIAL", decision="FAIL", second=0)
    r2, p2 = make_record("ME-EOL-002", attempt=1, relation="REPAIR_OF", decision="REWORK", parent=r1, second=3)
    r3, p3 = make_record("ME-EOL-003", attempt=2, relation="RETEST_OF", decision="PASS", parent=r2, second=6)
    r4, p4 = make_record("ME-EOL-004", attempt=2, relation="RELEASES", decision="RELEASED", parent=r3, second=9)
    package = {
        "schema_version": "1.0",
        "package_id": "urn:example:synthetic:pme:eol-rework-0001",
        "profile": {"id": "P-ME-EOL", "version": "1.0"},
        "created_at": "2026-08-27T00:00:20Z",
        "records": [r1, r2, r3, r4],
    }
    return package, {
        r1["raw_artifacts"][0]["uri"]: p1,
        r2["raw_artifacts"][0]["uri"]: p2,
        r3["raw_artifacts"][0]["uri"]: p3,
        r4["raw_artifacts"][0]["uri"]: p4,
    }


def write_package(root: Path, package: dict, artifacts: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for uri, payload in artifacts.items():
        target = root / uri
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (root / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
