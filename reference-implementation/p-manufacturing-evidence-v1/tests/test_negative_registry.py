from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pme.validator import validate_package
from support import record_hash, valid_rework_package, write_package


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "fixtures" / "negative-cases.json"


def rehash_chain(package: dict) -> None:
    by_id = {}
    for record in package["records"]:
        parents = record["lineage"].get("parent_evidence_ids") or []
        if parents and parents[0] in by_id:
            record["lineage"]["previous_record_hash"] = by_id[parents[0]]["integrity"]["record_sha256"]
        elif not parents:
            record["lineage"]["previous_record_hash"] = None
        record["integrity"]["record_sha256"] = record_hash(record)
        by_id.setdefault(record["evidence_id"], record)


def mutate(package: dict, artifacts: dict[str, bytes], name: str) -> None:
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
        records[2]["integrity"]["record_sha256"] = record_hash(records[2])
        return
    elif name == "wrong_previous_hash":
        records[2]["lineage"]["previous_record_hash"] = "0" * 64
        records[2]["integrity"]["record_sha256"] = record_hash(records[2])
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
        raise AssertionError(name)
    rehash_chain(package)


class NegativeRegistryTests(unittest.TestCase):
    def test_every_registered_mutation_hits_its_intended_required_test(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        failures = []
        for case in registry["cases"]:
            package, artifacts = valid_rework_package()
            package = copy.deepcopy(package)
            artifacts = dict(artifacts)
            mutate(package, artifacts, case["mutation"])
            with tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                write_package(root, package, artifacts)
                first_uri = package["records"][0]["raw_artifacts"][0]["uri"]
                if case["mutation"] == "missing_artifact":
                    (root / first_uri).unlink()
                elif case["mutation"] == "tamper_artifact":
                    (root / first_uri).write_bytes(b'{"tampered":true}')
                run = validate_package(root)
                by_id = {result.test_id: result for result in run.results}
                result = by_id[case["intended_test"]]
                if result.result == "PASS":
                    failures.append({"case_id": case["case_id"], "test_id": case["intended_test"], "result": result.result})
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
