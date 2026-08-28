from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_IDS = [f"CAE-T{i:03d}" for i in range(1, 21)]
LEVEL_ORDER = {"C0": 0, "C1": 1, "C2": 2, "C3": 3}
ROLE_BY_LEVEL = {
    "C0": "SUPPLIER_DECLARANT",
    "C1": "LAB_EVALUATOR",
    "C2": "FAT_SAT_EVALUATOR",
    "C3": "OPERATIONS_MONITOR",
}
PROOF_TYPES = {
    "MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT",
    "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE", "ATTESTATION", "EXCEPTION_RECORD",
}
REQUIRED_PROOFS = {
    "C0": {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"},
    "C1": {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT"},
    "C2": {"AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE"},
    "C3": {"AUTOMATED_TEST", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE"},
}
MATERIAL_BASELINE_KEYS = ("profile_version", "program_version", "parameter_hash", "interface_version")


@dataclass(frozen=True)
class ConformanceResult:
    test_id: str
    result: str
    reason: str
    observations: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssessmentRun:
    package_dir: Path
    package: dict[str, Any]
    results: list[ConformanceResult]
    metrics: dict[str, Any]
    lifecycle_state: str
    overall_decision: str
    evidence_trace: dict[str, Any]
    reevaluation: dict[str, Any]

    @property
    def required_failures(self) -> int:
        return sum(1 for row in self.results if row.result in {"FAIL", "BLOCKED"})

    @property
    def counts(self) -> dict[str, int]:
        return {name: sum(1 for row in self.results if row.result == name) for name in ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE")}


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must use RFC3339 UTC Z form")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_cac() -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[3]
    return json.loads((repo / "machine-readable" / "p0-08" / "conformance-criteria-v1.json").read_text(encoding="utf-8"))


def _metric_vector(sources: dict[str, Any]) -> dict[str, Any]:
    names = (
        "machine_readable_coverage", "requirement_testability", "automation_rate",
        "evidence_completeness", "applicable_required_pass_rate",
        "cross_implementation_reproducibility", "regression_stability", "c3_drift_closure_rate",
    )
    out: dict[str, Any] = {}
    for name in names:
        row = sources.get(name) or {}
        numerator = row.get("numerator")
        denominator = row.get("denominator")
        valid = isinstance(numerator, int) and isinstance(denominator, int) and numerator >= 0 and denominator >= 0 and numerator <= denominator
        if not valid:
            out[name] = {"numerator": numerator, "denominator": denominator, "status": "INVALID", "value": None}
        elif denominator == 0:
            out[name] = {"numerator": numerator, "denominator": denominator, "status": "NOT_APPLICABLE", "value": None}
        else:
            out[name] = {"numerator": numerator, "denominator": denominator, "status": "MEASURED", "value": numerator / denominator}
    return out


def _evidence_map(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("evidence_id")): row for row in package.get("evidence_refs") or [] if row.get("evidence_id")}


def _has_source_stage(package: dict[str, Any], stage: str) -> bool:
    return any(row.get("source_stage") == stage for row in package.get("evidence_refs") or [])


def _proof_types(package: dict[str, Any]) -> set[str]:
    return {str(row.get("proof_type")) for row in package.get("evidence_refs") or []}


def _chain_has(package: dict[str, Any], level: str) -> bool:
    return any(
        row.get("level") == level
        and row.get("decision") == "PASS"
        and row.get("lifecycle_state") == "VALID"
        for row in package.get("assurance_chain") or []
    )


def _upstream_blob_from_proof(package_dir: Path, package: dict[str, Any], standard_id: str) -> str | None:
    allowed_stages = {
        "R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION",
        "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE",
    }
    for ref in package.get("evidence_refs") or []:
        if ref.get("source_stage") not in allowed_stages:
            continue
        path = package_dir / str(ref.get("uri") or "")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("standard_id") == standard_id:
            return data.get("source_blob_sha")
    return None


def validate_package(package_dir: Path) -> AssessmentRun:
    package_dir = Path(package_dir)
    package_path = package_dir / "package.json"
    if not package_path.is_file():
        rows = [ConformanceResult(test_id, "BLOCKED", "package.json unavailable") for test_id in TEST_IDS]
        return AssessmentRun(package_dir, {}, rows, {}, "REEVALUATION_REQUIRED", "BLOCKED", {"bindings": []}, {"state": "REQUIRED", "triggers": ["PACKAGE_UNAVAILABLE"]})
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception as exc:
        rows = [ConformanceResult(test_id, "BLOCKED", f"package.json unreadable: {exc}") for test_id in TEST_IDS]
        return AssessmentRun(package_dir, {}, rows, {}, "REEVALUATION_REQUIRED", "BLOCKED", {"bindings": []}, {"state": "REQUIRED", "triggers": ["PACKAGE_UNREADABLE"]})

    criteria = _load_cac().get("criteria") or []
    checks: dict[str, tuple[bool, str, Any]] = {}
    level = package.get("assessment_level")
    level_index = LEVEL_ORDER.get(str(level), -1)

    checks["CAE-T001"] = (
        package.get("schema_version") == "1.0"
        and bool(package.get("assessment_id"))
        and (package.get("profile") or {}).get("id") == "P-CAE-AUTO-R14"
        and (package.get("profile") or {}).get("version") == "1.0"
        and level in LEVEL_ORDER
        and bool(package.get("assessment_time")),
        "assessment/package/schema/profile identity complete",
        {"assessment_id": package.get("assessment_id"), "level": level},
    )

    required_fields = {"requirement_id", "proof_type", "test_id", "automation_flag", "required", "applicability_rule", "decision_rule", "evidence_requirements"}
    test_ids = [row.get("test_id") for row in criteria]
    req_ids = [row.get("requirement_id") for row in criteria]
    checks["CAE-T002"] = (
        test_ids == TEST_IDS and len(req_ids) == len(set(req_ids)) == 20 and all(required_fields.issubset(row) for row in criteria),
        "CAC identifiers unique and Requirement/Proof/Test/Automation/Decision/Evidence binding complete",
        {"criteria_count": len(criteria)},
    )

    evidence_ok, evidence_bad = True, []
    for ref in package.get("evidence_refs") or []:
        uri = ref.get("uri")
        safe = isinstance(uri, str) and uri and "://" not in uri and not uri.startswith("/") and ".." not in Path(uri).parts
        path = package_dir / str(uri or "")
        try:
            ok = safe and path.is_file() and path.stat().st_size == int(ref.get("size_bytes")) and _sha256(path) == ref.get("sha256")
        except Exception:
            ok = False
        if not ok:
            evidence_ok = False
            evidence_bad.append(ref.get("evidence_id"))
    checks["CAE-T003"] = (evidence_ok and bool(package.get("evidence_refs")), "evidence URI/size/SHA-256 binding valid", evidence_bad)

    actual_proofs = _proof_types(package)
    checks["CAE-T004"] = (
        actual_proofs.issubset(PROOF_TYPES) and REQUIRED_PROOFS.get(str(level), set()).issubset(actual_proofs),
        "proof types valid and level-required proof set present",
        {"proof_types": sorted(actual_proofs)},
    )

    execution = package.get("execution_summary") or {}
    checks["CAE-T005"] = (
        execution.get("manual_passed_automatable") == 0
        and execution.get("automatable_required") == execution.get("automated_executed")
        and all(ref.get("execution_mode") == "AUTOMATED" for ref in package.get("evidence_refs") or [] if ref.get("proof_type") == "AUTOMATED_TEST"),
        "automatable required criteria executed automatically",
        execution,
    )

    checks["CAE-T006"] = (
        level in ROLE_BY_LEVEL
        and (package.get("assessor") or {}).get("role") == ROLE_BY_LEVEL.get(str(level))
        and bool((package.get("assessor") or {}).get("assessor_id")),
        "assessor role permitted for declared level",
        package.get("assessor"),
    )

    na_records = package.get("not_applicable") or []
    checks["CAE-T007"] = (
        all(row.get("permitted") is True and bool(row.get("justification")) for row in na_records),
        "NOT_APPLICABLE use is permitted and justified",
        na_records,
    )

    exceptions = package.get("exceptions") or []
    checks["CAE-T008"] = (
        all(row.get("masks_required_failure") is not True for row in exceptions),
        "exceptions do not mask required FAIL/BLOCKED",
        exceptions,
    )

    c0_ok = True
    if level == "C0":
        c0_ok = {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"}.issubset(actual_proofs)
    checks["CAE-T009"] = (c0_ok, "C0 supplier-declaration inputs complete when applicable", None)

    c1_ok = True
    if level == "C1":
        c1_ok = (
            _chain_has(package, "C0")
            and "LAB_REPORT" in actual_proofs
            and _has_source_stage(package, "R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION")
        )
    elif level_index > LEVEL_ORDER["C1"]:
        c1_ok = _chain_has(package, "C0") and _chain_has(package, "C1")
    checks["CAE-T010"] = (c1_ok, "C1 predecessor and lab/TCK evidence valid or inherited through a valid C1 assessment", None)

    c2_ok = True
    if level_index >= LEVEL_ORDER["C2"]:
        binding = package.get("project_binding") or {}
        c2_ok = (
            _chain_has(package, "C1")
            and bool(binding.get("project_id"))
            and bool(binding.get("instance_id"))
            and _has_source_stage(package, "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE")
        )
    checks["CAE-T011"] = (c2_ok, "C2 predecessor/project binding/P0-06 proof valid when applicable", None)

    c3_ok = True
    if level == "C3":
        monitoring = package.get("continuous_monitoring") or {}
        try:
            start = _parse_utc(monitoring.get("window_start"))
            end = _parse_utc(monitoring.get("window_end"))
            coverage_days = (end - start).total_seconds() / 86400
            c3_ok = (
                _chain_has(package, "C2")
                and monitoring.get("coverage_ratio") == 1.0
                and coverage_days >= int(monitoring.get("required_days", 0))
                and "CONTINUOUS_EVIDENCE" in actual_proofs
            )
        except Exception:
            c3_ok = False
    checks["CAE-T012"] = (c3_ok, "C3 predecessor and continuous observation coverage valid when applicable", None)

    # T013 verifies that the declared assessment baseline is complete and that
    # immutable upstream proof snapshots are hash-bound to that baseline. The
    # observed baseline may legitimately differ later; that difference is a
    # lifecycle drift handled by T014/T015, not a data-integrity failure here.
    baseline = package.get("baseline") or {}
    observed = package.get("observed_baseline") or {}
    baseline_ok = all(
        baseline.get(key) not in (None, "") and observed.get(key) not in (None, "")
        for key in MATERIAL_BASELINE_KEYS
    )
    p002_blob = _upstream_blob_from_proof(package_dir, package, "P0-02")
    p006_blob = _upstream_blob_from_proof(package_dir, package, "P0-06")
    if p002_blob is not None:
        baseline_ok = baseline_ok and p002_blob == baseline.get("p0_02_status_blob_sha")
    if p006_blob is not None:
        baseline_ok = baseline_ok and p006_blob == baseline.get("p0_06_status_blob_sha")
    checks["CAE-T013"] = (
        baseline_ok,
        "declared baseline complete and upstream proof snapshots hash-bound",
        {"p0_02": p002_blob, "p0_06": p006_blob},
    )

    material_drift = (
        any(baseline.get(key) != observed.get(key) for key in MATERIAL_BASELINE_KEYS)
        or any(row.get("material") is True and row.get("status") != "CLOSED" for row in package.get("drifts") or [])
    )
    checks["CAE-T014"] = (
        package.get("declared_material_drift") is material_drift,
        "material drift detection deterministic",
        {"computed_material_drift": material_drift},
    )

    validity = package.get("validity") or {}
    try:
        assessment_time = _parse_utc(package.get("assessment_time"))
        valid_from = _parse_utc(validity.get("valid_from"))
        valid_until = _parse_utc(validity.get("valid_until"))
        expired = assessment_time > valid_until
        not_yet_valid = assessment_time < valid_from
    except Exception:
        expired = True
        not_yet_valid = True
    revoked = validity.get("revoked") is True
    superseded = validity.get("superseded") is True
    triggers = []
    if material_drift:
        triggers.append("MATERIAL_DRIFT")
    if expired:
        triggers.append("EXPIRED")
    if revoked:
        triggers.append("REVOKED")
    if superseded:
        triggers.append("SUPERSEDED")
    expected_reeval = "REQUIRED" if triggers else "NOT_REQUIRED"
    checks["CAE-T015"] = (
        package.get("claimed_reevaluation_state") == expected_reeval,
        "reevaluation trigger state deterministic",
        {"expected": expected_reeval, "triggers": triggers},
    )

    checks["CAE-T016"] = (
        not expired and not not_yet_valid and not revoked and not superseded,
        "validity/effectivity/revocation/supersession internally consistent",
        validity,
    )

    outcomes = [row.get("result") for row in package.get("required_outcomes") or []]
    if "FAIL" in outcomes:
        input_decision = "FAIL"
    elif "BLOCKED" in outcomes:
        input_decision = "BLOCKED"
    else:
        input_decision = "PASS"
    checks["CAE-T017"] = (
        bool(outcomes) and package.get("declared_decision") == input_decision and "weighted_score" not in package,
        "overall decision deterministic with FAIL>BLOCKED>PASS and no weighted score",
        {"computed": input_decision},
    )

    metrics = _metric_vector(package.get("effectiveness_sources") or {})
    checks["CAE-T018"] = (
        metrics == (package.get("claimed_effectiveness_metrics") or {})
        and all(row.get("status") != "INVALID" for row in metrics.values()),
        "effectiveness metric vector reproducible from source counters",
        metrics,
    )

    evidence_ids = set(_evidence_map(package))
    binding_by_test = {row.get("test_id"): row for row in package.get("trace_bindings") or []}
    trace_ok = True
    for criterion in criteria:
        test_id = criterion.get("test_id")
        binding = binding_by_test.get(test_id) or {}
        if (
            binding.get("requirement_id") != criterion.get("requirement_id")
            or not binding.get("evidence_ids")
            or any(eid not in evidence_ids for eid in binding.get("evidence_ids") or [])
        ):
            trace_ok = False
            break
    checks["CAE-T019"] = (
        trace_ok and len(binding_by_test) == 20,
        "Requirement→Test→Proof/Evidence trace complete",
        {"binding_count": len(binding_by_test)},
    )

    signature_state = package.get("signature_state")
    statement_ok = (
        package.get("certification_claim") is False
        and package.get("statement_type") == "CONFORMITY_EVALUATION_STATEMENT"
        and signature_state in {"UNSIGNED", "SIGNED_VERIFIED", "SIGNED_UNVERIFIED"}
    )
    if signature_state == "UNSIGNED":
        statement_ok = statement_ok and not package.get("signature")
    checks["CAE-T020"] = (
        statement_ok,
        "conformity statement truthful and certification_claim=false",
        {"signature_state": signature_state},
    )

    results = [
        ConformanceResult(test_id, "PASS" if checks[test_id][0] else "FAIL", checks[test_id][1], checks[test_id][2])
        for test_id in TEST_IDS
    ]

    if revoked:
        lifecycle = "REVOKED"
    elif superseded:
        lifecycle = "SUPERSEDED"
    elif expired:
        lifecycle = "EXPIRED"
    elif material_drift:
        lifecycle = "REEVALUATION_REQUIRED"
    else:
        lifecycle = "VALID"

    if any(row.result == "FAIL" for row in results):
        overall = "FAIL"
    elif any(row.result == "BLOCKED" for row in results):
        overall = "BLOCKED"
    else:
        overall = input_decision

    trace = {
        "schema_version": "1.0",
        "assessment_id": package.get("assessment_id"),
        "bindings": package.get("trace_bindings") or [],
        "evidence_refs": package.get("evidence_refs") or [],
    }
    reevaluation = {
        "schema_version": "1.0",
        "state": expected_reeval,
        "triggers": triggers,
        "lifecycle_state": lifecycle,
    }
    return AssessmentRun(package_dir, package, results, metrics, lifecycle, overall, trace, reevaluation)
