from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, file_sha256, record_sha256
from .trace import build_trace_graph, trace_release

TEST_IDS = [f"ME-T{i:03d}" for i in range(1, 19)]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELATIONS = {"INITIAL", "REPAIR_OF", "RETEST_OF", "RELEASES"}
DECISIONS = {"PASS", "FAIL", "REWORK", "RETEST", "RELEASED"}
EXPECTED_EOL_PROGRAM_ID = "EOL_REFERENCE"
EXPECTED_EOL_PROGRAM_VERSION = "1.0.0"
EXPECTED_EOL_PARAMETER_SET_ID = "EOL-PARAM-001"
EXPECTED_EOL_PARAMETER_HASH = "9722e9a83b3ac4c91b70b9f5af5b323da502d79b6964436c999a2385acc79f11"


@dataclass(frozen=True)
class ConformanceResult:
    test_id: str
    result: str
    reason: str
    observations: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationRun:
    package_dir: Path
    package: dict[str, Any]
    results: list[ConformanceResult]
    trace_graph: dict[str, Any]
    trace_query: dict[str, Any]

    @property
    def required_failures(self) -> int:
        return sum(1 for r in self.results if r.result in {"FAIL", "BLOCKED"})

    @property
    def counts(self) -> dict[str, int]:
        return {name: sum(1 for r in self.results if r.result == name) for name in ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE")}


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be RFC3339 UTC with Z suffix")
    dt = datetime.fromisoformat(value[:-1] + "+00:00")
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError("timestamp must be UTC")
    return dt


def _nonempty(mapping: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(mapping.get(key) not in (None, "", []) for key in keys)


def _record_map(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("evidence_id")): r for r in package.get("records") or [] if r.get("evidence_id")}


def _same_subject_operation(a: dict[str, Any], b: dict[str, Any]) -> bool:
    sa, sb = a.get("subject") or {}, b.get("subject") or {}
    return (sa.get("subject_id"), sa.get("operation_id")) == (sb.get("subject_id"), sb.get("operation_id"))


def validate_package(package_dir: Path) -> ValidationRun:
    package_dir = Path(package_dir)
    package_path = package_dir / "package.json"
    if not package_path.is_file():
        results = [ConformanceResult(tid, "BLOCKED", "package.json is unavailable") for tid in TEST_IDS]
        return ValidationRun(package_dir, {}, results, {"schema_version": "1.0", "nodes": [], "edges": []}, {"complete": False})
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception as exc:
        results = [ConformanceResult(tid, "BLOCKED", f"package.json is unreadable: {exc}") for tid in TEST_IDS]
        return ValidationRun(package_dir, {}, results, {"schema_version": "1.0", "nodes": [], "edges": []}, {"complete": False})

    records = package.get("records") if isinstance(package.get("records"), list) else []
    by_id = _record_map(package)
    graph = build_trace_graph(package)
    release_ids = [r.get("evidence_id") for r in records if (r.get("disposition") or {}).get("decision") == "RELEASED" and r.get("evidence_id")]
    trace_query = trace_release(graph, str(release_ids[-1])) if release_ids else {"complete": False, "release_evidence_id": None}
    checks: dict[str, tuple[bool, str, Any]] = {}

    checks["ME-T001"] = (
        package.get("schema_version") == "1.0"
        and bool(package.get("package_id"))
        and isinstance(package.get("profile"), dict)
        and package["profile"].get("id") == "P-ME-EOL"
        and package["profile"].get("version") == "1.0"
        and bool(records),
        "package/schema/profile identity present",
        {"package_id": package.get("package_id"), "record_count": len(records)},
    )

    ids = [r.get("evidence_id") for r in records]
    checks["ME-T002"] = (all(isinstance(x, str) and x for x in ids) and len(ids) == len(set(ids)), "evidence ids are unique", ids)

    provenance_ok, provenance_missing = True, []
    for r in records:
        source = r.get("source") or {}
        if not _nonempty(source, ("system_id", "equipment_id", "source_record_id")):
            provenance_ok = False
            provenance_missing.append(r.get("evidence_id"))
    checks["ME-T003"] = (provenance_ok, "source provenance complete", provenance_missing)

    link_ok, link_bad = True, []
    for r in records:
        subject, process, source = r.get("subject") or {}, r.get("process_context") or {}, r.get("source") or {}
        ok = _nonempty(subject, ("subject_id", "subject_type", "operation_id")) and _nonempty(process, ("process_id", "station_id", "equipment_id")) and process.get("equipment_id") == source.get("equipment_id")
        if not ok:
            link_ok = False
            link_bad.append(r.get("evidence_id"))
        for pid in (r.get("lineage") or {}).get("parent_evidence_ids") or []:
            if pid in by_id and not _same_subject_operation(r, by_id[pid]):
                link_ok = False
                link_bad.append(r.get("evidence_id"))
    checks["ME-T004"] = (link_ok, "subject/process/equipment linkage complete and consistent", link_bad)

    version_ok, version_bad = True, []
    for r in records:
        ex = r.get("execution_context") or {}
        ok = _nonempty(ex, ("program_id", "program_version", "parameter_set_id", "parameter_hash", "tool_state")) and bool(HEX64.fullmatch(str(ex.get("parameter_hash") or "")))
        if r.get("profile_id") == "P-ME-EOL" or package.get("profile", {}).get("id") == "P-ME-EOL":
            ok = (
                ok
                and ex.get("program_id") == EXPECTED_EOL_PROGRAM_ID
                and ex.get("program_version") == EXPECTED_EOL_PROGRAM_VERSION
                and ex.get("parameter_set_id") == EXPECTED_EOL_PARAMETER_SET_ID
                and ex.get("parameter_hash") == EXPECTED_EOL_PARAMETER_HASH
            )
        if not ok:
            version_ok = False
            version_bad.append(r.get("evidence_id"))
    checks["ME-T005"] = (version_ok, "program/parameter version binding complete", version_bad)

    time_ok, time_bad, event_times = True, [], {}
    for r in records:
        try:
            event = _parse_utc((r.get("time") or {}).get("event_time"))
            collected = _parse_utc((r.get("time") or {}).get("collected_time"))
            event_times[str(r.get("evidence_id"))] = event
            if collected < event:
                raise ValueError("collection time precedes event time")
        except Exception:
            time_ok = False
            time_bad.append(r.get("evidence_id"))
    for r in records:
        event = event_times.get(str(r.get("evidence_id")))
        for pid in (r.get("lineage") or {}).get("parent_evidence_ids") or []:
            if event and pid in event_times and event < event_times[pid]:
                time_ok = False
                time_bad.append(r.get("evidence_id"))
    checks["ME-T006"] = (time_ok, "timestamps are UTC and lineage order is nondecreasing", sorted(set(time_bad), key=str))

    measurement_ok, measurement_bad = True, []
    for r in records:
        m = r.get("measurement") or {}
        ok = _nonempty(m, ("characteristic_id", "unit", "judgment")) and "raw_value" in m and "result_value" in m and m.get("judgment") in {"PASS", "FAIL", "REWORK", "RELEASED"}
        if not ok:
            measurement_ok = False
            measurement_bad.append(r.get("evidence_id"))
    checks["ME-T007"] = (measurement_ok, "measurement raw/result/unit/judgment complete", measurement_bad)

    uncertainty_ok, uncertainty_bad = True, []
    for r in records:
        u = (r.get("measurement") or {}).get("uncertainty")
        ok = isinstance(u, dict) and ((_nonempty(u, ("unit", "method")) and isinstance(u.get("value"), (int, float))) or bool(u.get("not_applicable_reason")))
        if not ok:
            uncertainty_ok = False
            uncertainty_bad.append(r.get("evidence_id"))
    checks["ME-T008"] = (uncertainty_ok, "measurement uncertainty explicitly declared", uncertainty_bad)

    artifact_ok, artifact_bad = True, []
    for r in records:
        artifacts = r.get("raw_artifacts") or []
        if not artifacts:
            artifact_ok = False
            artifact_bad.append(r.get("evidence_id"))
            continue
        for a in artifacts:
            uri = a.get("uri")
            safe_uri = isinstance(uri, str) and uri and "://" not in uri and not uri.startswith("/") and ".." not in Path(uri).parts
            if not safe_uri:
                artifact_ok = False
                artifact_bad.append(r.get("evidence_id"))
                continue
            path = package_dir / uri
            try:
                ok = path.is_file() and path.stat().st_size == int(a.get("size_bytes")) and file_sha256(path) == a.get("sha256")
            except Exception:
                ok = False
            if not ok:
                artifact_ok = False
                artifact_bad.append(r.get("evidence_id"))
    checks["ME-T009"] = (artifact_ok, "raw artifacts exist and size/SHA-256 match", sorted(set(artifact_bad), key=str))

    record_hash_ok, record_hash_bad = True, []
    for r in records:
        expected = (r.get("integrity") or {}).get("record_sha256")
        if not isinstance(expected, str) or not HEX64.fullmatch(expected) or record_sha256(r) != expected:
            record_hash_ok = False
            record_hash_bad.append(r.get("evidence_id"))
    checks["ME-T010"] = (record_hash_ok, "canonical record hashes match", record_hash_bad)

    parents_ok, parent_bad = True, []
    for r in records:
        eid = r.get("evidence_id")
        for pid in (r.get("lineage") or {}).get("parent_evidence_ids") or []:
            if pid == eid or pid not in by_id:
                parents_ok = False
                parent_bad.append(eid)
    checks["ME-T011"] = (parents_ok, "parent evidence references resolve", parent_bad)

    prev_ok, prev_bad = True, []
    for r in records:
        lineage = r.get("lineage") or {}
        parents = lineage.get("parent_evidence_ids") or []
        previous = lineage.get("previous_record_hash")
        if not parents:
            ok = previous in (None, "")
        else:
            first = by_id.get(parents[0])
            ok = bool(first) and previous == (first.get("integrity") or {}).get("record_sha256")
        if not ok:
            prev_ok = False
            prev_bad.append(r.get("evidence_id"))
    checks["ME-T012"] = (prev_ok, "previous-record hash matches lineage parent", prev_bad)

    attempt_ok, attempt_bad, groups = True, [], {}
    for r in records:
        s = r.get("subject") or {}
        groups.setdefault((s.get("subject_id"), s.get("operation_id")), []).append(r)
    for group in groups.values():
        attempts, prev = [], None
        for r in sorted(group, key=lambda x: event_times.get(str(x.get("evidence_id")), datetime.min.replace(tzinfo=timezone.utc))):
            attempt = (r.get("lineage") or {}).get("attempt_no")
            if not isinstance(attempt, int) or attempt < 1:
                attempt_ok = False
                attempt_bad.append(r.get("evidence_id"))
                continue
            attempts.append(attempt)
            if prev is not None and attempt < prev:
                attempt_ok = False
                attempt_bad.append(r.get("evidence_id"))
            prev = attempt
        if attempts and set(attempts) != set(range(1, max(attempts) + 1)):
            attempt_ok = False
            attempt_bad.extend(r.get("evidence_id") for r in group)
    checks["ME-T013"] = (attempt_ok, "attempt numbers are monotonic and contiguous", sorted(set(attempt_bad), key=str))

    relation_ok, relation_bad = True, []
    for r in records:
        lineage = r.get("lineage") or {}
        relation = lineage.get("relation")
        parents = lineage.get("parent_evidence_ids") or []
        decision = (r.get("disposition") or {}).get("decision")
        attempt = lineage.get("attempt_no")
        ok = relation in RELATIONS and decision in DECISIONS
        if relation == "INITIAL":
            ok = ok and not parents and decision in {"PASS", "FAIL"}
        elif len(parents) != 1 or parents[0] not in by_id:
            ok = False
        else:
            parent = by_id[parents[0]]
            pdecision = (parent.get("disposition") or {}).get("decision")
            pattempt = (parent.get("lineage") or {}).get("attempt_no")
            if relation == "REPAIR_OF":
                ok = ok and decision == "REWORK" and pdecision in {"FAIL", "REWORK"} and attempt == pattempt
            elif relation == "RETEST_OF":
                ok = ok and decision in {"PASS", "FAIL"} and pdecision in {"FAIL", "REWORK"} and isinstance(pattempt, int) and attempt == pattempt + 1
            elif relation == "RELEASES":
                ok = ok and decision == "RELEASED" and pdecision == "PASS" and attempt == pattempt
        if not ok:
            relation_ok = False
            relation_bad.append(r.get("evidence_id"))
    checks["ME-T014"] = (relation_ok, "retest/rework/release relation semantics are legal", relation_bad)

    release_ok, release_bad = bool(release_ids), []
    for r in records:
        if (r.get("disposition") or {}).get("decision") != "RELEASED":
            continue
        parents = (r.get("lineage") or {}).get("parent_evidence_ids") or []
        ok = len(parents) == 1 and parents[0] in by_id
        if ok:
            parent = by_id[parents[0]]
            ok = (parent.get("disposition") or {}).get("decision") == "PASS" and _same_subject_operation(r, parent)
        if not ok:
            release_ok = False
            release_bad.append(r.get("evidence_id"))
    checks["ME-T015"] = (release_ok, "release has a PASS predecessor for the same subject/operation", release_bad)

    edge_index = {(e["source"], e["type"], e["target"]) for e in graph.get("edges") or []}
    graph_ok, graph_bad = True, []
    for r in records:
        eid = str(r.get("evidence_id") or "")
        subject = str((r.get("subject") or {}).get("subject_id") or "")
        source_record = str((r.get("source") or {}).get("source_record_id") or "")
        equipment = str((r.get("process_context") or {}).get("equipment_id") or "")
        ex = r.get("execution_context") or {}
        program = f"program:{ex.get('program_id','')}@{ex.get('program_version','')}"
        parameter = f"parameter:{ex.get('parameter_set_id','')}@{ex.get('parameter_hash','')}"
        mandatory = [
            (eid, "SUBJECT_OF", subject),
            (eid, "GENERATED_BY", "source:" + source_record),
            (eid, "GENERATED_BY", equipment),
            (eid, "USES_PROGRAM", program),
            (eid, "USES_PARAMETER_SET", parameter),
        ]
        mandatory.extend((eid, "HAS_RAW_ARTIFACT", "artifact:" + str(a.get("artifact_id") or a.get("uri") or "")) for a in r.get("raw_artifacts") or [])
        if any(item not in edge_index for item in mandatory):
            graph_ok = False
            graph_bad.append(r.get("evidence_id"))
    checks["ME-T016"] = (graph_ok, "trace graph contains mandatory provenance edges", graph_bad)

    checks["ME-T017"] = (
        bool(trace_query.get("complete"))
        and bool(trace_query.get("source_records"))
        and bool(trace_query.get("equipment"))
        and bool(trace_query.get("programs"))
        and bool(trace_query.get("parameter_sets"))
        and bool(trace_query.get("artifacts")),
        "release trace query resolves source/program/parameter/equipment/artifact",
        trace_query,
    )

    try:
        round_trip = json.loads(canonical_json_bytes(package).decode("utf-8"))
        readable = round_trip == package and all((package_dir / a.get("uri", "")).is_file() for r in records for a in r.get("raw_artifacts") or [])
    except Exception:
        readable = False
    checks["ME-T018"] = (readable, "package round-trip is deterministic/readable using JSON + raw artifacts", None)

    results = [ConformanceResult(tid, "PASS" if checks[tid][0] else "FAIL", checks[tid][1], checks[tid][2]) for tid in TEST_IDS]
    return ValidationRun(package_dir, package, results, graph, trace_query)
