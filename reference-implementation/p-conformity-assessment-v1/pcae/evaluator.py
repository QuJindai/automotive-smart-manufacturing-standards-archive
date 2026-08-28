from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_IDS = [f"CAE-T{i:03d}" for i in range(1, 21)]
LEVEL_ORDER = {"C0": 0, "C1": 1, "C2": 2, "C3": 3}
ROLE_BY_LEVEL = {"C0": "SUPPLIER_DECLARANT", "C1": "LAB_EVALUATOR", "C2": "FAT_SAT_EVALUATOR", "C3": "OPERATIONS_MONITOR"}
PROOF_TYPES = {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE", "ATTESTATION", "EXCEPTION_RECORD"}
REQUIRED_PROOFS = {
    "C0": {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"},
    "C1": {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "ATTESTATION"},
    "C2": {"AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "ATTESTATION"},
    "C3": {"AUTOMATED_TEST", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE", "ATTESTATION"},
}
MATERIAL_BASELINE_KEYS = ("profile_version", "program_version", "parameter_hash", "interface_version")
UPSTREAM = {
    "P0-02": ("R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION", "p0_02_status_blob_sha"),
    "P0-06": ("R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE", "p0_06_status_blob_sha"),
}
METRIC_NAMES = (
    "machine_readable_coverage", "requirement_testability", "automation_rate",
    "evidence_completeness", "applicable_required_pass_rate",
    "cross_implementation_reproducibility", "regression_stability", "c3_drift_closure_rate",
)


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


def _evidence_map(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("evidence_id")): row for row in package.get("evidence_refs") or [] if row.get("evidence_id")}


def _proof_types(package: dict[str, Any]) -> set[str]:
    return {str(row.get("proof_type")) for row in package.get("evidence_refs") or []}


def _ref_valid(package_dir: Path, ref: dict[str, Any]) -> bool:
    uri = ref.get("uri")
    safe = isinstance(uri, str) and uri and "://" not in uri and not uri.startswith("/") and ".." not in Path(uri).parts
    if not safe:
        return False
    path = package_dir / uri
    try:
        return path.is_file() and path.stat().st_size == int(ref.get("size_bytes")) and _sha256(path) == ref.get("sha256")
    except Exception:
        return False


def _json_proof(package_dir: Path, ref: dict[str, Any]) -> dict[str, Any] | None:
    if not _ref_valid(package_dir, ref):
        return None
    try:
        value = json.loads((package_dir / str(ref.get("uri"))).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _upstream_proof(package_dir: Path, package: dict[str, Any], standard_id: str) -> dict[str, Any] | None:
    stage, baseline_field = UPSTREAM[standard_id]
    baseline = package.get("baseline") or {}
    for ref in package.get("evidence_refs") or []:
        if ref.get("source_stage") != stage:
            continue
        proof = _json_proof(package_dir, ref)
        if not proof:
            continue
        if (
            proof.get("standard_id") == standard_id
            and proof.get("source_stage") == stage
            and proof.get("status") == "PASS"
            and proof.get("required_failures") == 0
            and proof.get("source_blob_sha") == baseline.get(baseline_field)
            and proof.get("certification_claim") is False
        ):
            return proof
    return None


def _chain_valid(package_dir: Path, package: dict[str, Any], level: str, assessment_time: datetime) -> bool:
    refs = _evidence_map(package)
    for row in package.get("assurance_chain") or []:
        if row.get("level") != level:
            continue
        evidence_id = row.get("evidence_id")
        ref = refs.get(str(evidence_id))
        if not ref or ref.get("proof_type") != "ATTESTATION":
            return False
        proof = _json_proof(package_dir, ref)
        if not proof:
            return False
        try:
            valid_until = _parse_utc(row.get("valid_until"))
        except Exception:
            return False
        return (
            assessment_time <= valid_until
            and row.get("decision") == "PASS"
            and row.get("lifecycle_state") == "VALID"
            and bool(row.get("assessment_id"))
            and proof.get("statement_type") == "CONFORMITY_EVALUATION_STATEMENT"
            and proof.get("assessment_id") == row.get("assessment_id")
            and proof.get("assessment_level") == row.get("level")
            and proof.get("decision") == row.get("decision")
            and proof.get("lifecycle_state") == row.get("lifecycle_state")
            and proof.get("valid_until") == row.get("valid_until")
            and proof.get("certification_claim") is False
        )
    return False


def _metric_vector(
    sources: dict[str, Any], evidence_ids: set[str], expected_automatable: int,
    valid_evidence_count: int, required_outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pass_count = sum(1 for row in required_outcomes if row.get("result") == "PASS")
    for name in METRIC_NAMES:
        row = sources.get(name) or {}
        numerator, denominator = row.get("numerator"), row.get("denominator")
        refs = row.get("source_evidence_ids")
        valid = (
            isinstance(numerator, int) and isinstance(denominator, int)
            and numerator >= 0 and denominator >= 0 and numerator <= denominator
            and isinstance(refs, list) and bool(refs) and set(refs).issubset(evidence_ids)
        )
        if name == "requirement_testability":
            valid = valid and numerator == len(TEST_IDS) and denominator == len(TEST_IDS)
        elif name == "automation_rate":
            valid = valid and numerator == expected_automatable and denominator == expected_automatable
        elif name == "evidence_completeness":
            valid = valid and numerator == valid_evidence_count and denominator == len(evidence_ids)
        elif name == "applicable_required_pass_rate":
            valid = valid and numerator == pass_count and denominator == len(required_outcomes)
        if not valid:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "INVALID", "value": None}
        elif denominator == 0:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "NOT_APPLICABLE", "value": None}
        else:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "MEASURED", "value": numerator / denominator}
    return out


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

    cac = _load_cac()
    criteria = cac.get("criteria") or []
    criteria_by_test = {row.get("test_id"): row for row in criteria}
    checks: dict[str, tuple[bool, str, Any]] = {}
    level = package.get("assessment_level")
    level_index = LEVEL_ORDER.get(str(level), -1)
    try:
        assessment_time = _parse_utc(package.get("assessment_time"))
    except Exception:
        assessment_time = datetime.max.replace(tzinfo=timezone.utc)

    checks["CAE-T001"] = (
        package.get("schema_version") == "1.0" and bool(package.get("assessment_id"))
        and (package.get("profile") or {}).get("id") == "P-CAE-AUTO-R14"
        and (package.get("profile") or {}).get("version") == "1.0" and level in LEVEL_ORDER,
        "assessment/package/schema/profile identity complete", {"assessment_id": package.get("assessment_id"), "level": level},
    )

    required_fields = {"requirement_id", "proof_type", "test_id", "automation_flag", "required", "na_allowed", "applicability_rule", "decision_rule", "evidence_requirements"}
    test_ids = [row.get("test_id") for row in criteria]
    req_ids = [row.get("requirement_id") for row in criteria]
    checks["CAE-T002"] = (
        test_ids == TEST_IDS and len(req_ids) == len(set(req_ids)) == 20 and all(required_fields.issubset(row) for row in criteria),
        "CAC identifiers unique and authoritative binding complete", {"criteria_count": len(criteria)},
    )

    evidence_refs = package.get("evidence_refs") or []
    valid_refs = {str(ref.get("evidence_id")) for ref in evidence_refs if ref.get("evidence_id") and _ref_valid(package_dir, ref)}
    evidence_ids = {str(ref.get("evidence_id")) for ref in evidence_refs if ref.get("evidence_id")}
    checks["CAE-T003"] = (
        bool(evidence_refs) and len(valid_refs) == len(evidence_refs) == len(evidence_ids),
        "evidence URI/size/SHA-256 binding valid", sorted(evidence_ids - valid_refs),
    )

    actual_proofs = _proof_types(package)
    checks["CAE-T004"] = (
        actual_proofs.issubset(PROOF_TYPES) and REQUIRED_PROOFS.get(str(level), set()).issubset(actual_proofs),
        "proof types valid and level-required proof set present", {"proof_types": sorted(actual_proofs)},
    )

    expected_automatable = sum(1 for row in criteria if row.get("required") is True and row.get("automation_flag") is True)
    execution = package.get("execution_summary") or {}
    checks["CAE-T005"] = (
        execution.get("manual_passed_automatable") == 0
        and execution.get("automatable_required") == expected_automatable
        and execution.get("automated_executed") == expected_automatable
        and all(ref.get("execution_mode") == "AUTOMATED" for ref in evidence_refs if ref.get("proof_type") == "AUTOMATED_TEST"),
        "automation counts derived from CAC and automatable criteria executed automatically",
        {"expected_automatable": expected_automatable, **execution},
    )

    checks["CAE-T006"] = (
        level in ROLE_BY_LEVEL and (package.get("assessor") or {}).get("role") == ROLE_BY_LEVEL.get(str(level))
        and bool((package.get("assessor") or {}).get("assessor_id")),
        "assessor role permitted for declared level", package.get("assessor"),
    )

    na_records = package.get("not_applicable") or []
    na_ok = True
    for row in na_records:
        criterion = criteria_by_test.get(row.get("test_id"))
        if not criterion or criterion.get("na_allowed") is not True or not bool(row.get("justification")):
            na_ok = False
            break
    checks["CAE-T007"] = (na_ok, "NOT_APPLICABLE permission comes from CAC and requires justification", na_records)

    exceptions = package.get("exceptions") or []
    checks["CAE-T008"] = (all(row.get("masks_required_failure") is not True for row in exceptions), "exceptions do not mask required FAIL/BLOCKED", exceptions)

    checks["CAE-T009"] = (
        level != "C0" or {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"}.issubset(actual_proofs),
        "C0 supplier-declaration inputs complete when applicable", None,
    )

    p002 = _upstream_proof(package_dir, package, "P0-02")
    p006 = _upstream_proof(package_dir, package, "P0-06")
    c0_chain = _chain_valid(package_dir, package, "C0", assessment_time) if level_index >= 1 else True
    c1_chain = _chain_valid(package_dir, package, "C1", assessment_time) if level_index >= 2 else True
    c2_chain = _chain_valid(package_dir, package, "C2", assessment_time) if level_index >= 3 else True

    if level == "C1":
        c1_ok = c0_chain and "LAB_REPORT" in actual_proofs and p002 is not None
    elif level_index > 1:
        c1_ok = c0_chain and c1_chain
    else:
        c1_ok = True
    checks["CAE-T010"] = (c1_ok, "C1 proof or inherited hash-bound C1 assessment valid", None)

    if level_index >= 2:
        binding = package.get("project_binding") or {}
        c2_ok = c1_chain and bool(binding.get("project_id")) and bool(binding.get("instance_id")) and p006 is not None
    else:
        c2_ok = True
    checks["CAE-T011"] = (c2_ok, "C2 predecessor/project binding/authoritative P0-06 proof valid when applicable", None)

    c3_ok = True
    if level == "C3":
        monitoring = package.get("continuous_monitoring") or {}
        try:
            start, end = _parse_utc(monitoring.get("window_start")), _parse_utc(monitoring.get("window_end"))
            coverage_days = (end - start).total_seconds() / 86400
            c3_ok = c2_chain and monitoring.get("coverage_ratio") == 1.0 and coverage_days >= int(monitoring.get("required_days", 0)) and "CONTINUOUS_EVIDENCE" in actual_proofs
        except Exception:
            c3_ok = False
    checks["CAE-T012"] = (c3_ok, "C3 hash-bound predecessor and observation coverage valid when applicable", None)

    baseline = package.get("baseline") or {}
    observed = package.get("observed_baseline") or {}
    baseline_ok = all(baseline.get(key) not in (None, "") and observed.get(key) not in (None, "") for key in MATERIAL_BASELINE_KEYS)
    if level_index >= 1:
        baseline_ok = baseline_ok and p002 is not None
    if level_index >= 2:
        baseline_ok = baseline_ok and p006 is not None
    checks["CAE-T013"] = (baseline_ok, "declared baseline complete and authoritative upstream proof snapshots hash-bound", {"p0_02": bool(p002), "p0_06": bool(p006)})

    material_drift = any(baseline.get(key) != observed.get(key) for key in MATERIAL_BASELINE_KEYS) or any(row.get("material") is True and row.get("status") != "CLOSED" for row in package.get("drifts") or [])
    checks["CAE-T014"] = (package.get("declared_material_drift") is material_drift, "material drift detection deterministic", {"computed_material_drift": material_drift})

    validity = package.get("validity") or {}
    try:
        valid_from, valid_until = _parse_utc(validity.get("valid_from")), _parse_utc(validity.get("valid_until"))
        expired, not_yet_valid = assessment_time > valid_until, assessment_time < valid_from
    except Exception:
        expired, not_yet_valid = True, True
    revoked, superseded = validity.get("revoked") is True, validity.get("superseded") is True
    triggers = (["MATERIAL_DRIFT"] if material_drift else []) + (["EXPIRED"] if expired else []) + (["REVOKED"] if revoked else []) + (["SUPERSEDED"] if superseded else [])
    expected_reeval = "REQUIRED" if triggers else "NOT_REQUIRED"
    checks["CAE-T015"] = (package.get("claimed_reevaluation_state") == expected_reeval, "reevaluation trigger state deterministic", {"expected": expected_reeval, "triggers": triggers})
    checks["CAE-T016"] = (not expired and not not_yet_valid and not revoked and not superseded, "validity/effectivity/revocation/supersession internally consistent", validity)

    required_outcomes = package.get("required_outcomes") or []
    outcomes = [row.get("result") for row in required_outcomes]
    input_decision = "FAIL" if "FAIL" in outcomes else "BLOCKED" if "BLOCKED" in outcomes else "PASS"
    checks["CAE-T017"] = (bool(outcomes) and package.get("declared_decision") == input_decision and "weighted_score" not in package, "overall decision deterministic with FAIL>BLOCKED>PASS and no weighted score", {"computed": input_decision})

    metrics = _metric_vector(package.get("effectiveness_sources") or {}, evidence_ids, expected_automatable, len(valid_refs), required_outcomes)
    checks["CAE-T018"] = (
        metrics == (package.get("claimed_effectiveness_metrics") or {}) and all(row.get("status") != "INVALID" for row in metrics.values()),
        "effectiveness vector reproducible from CAC, outcomes and evidence-sourced counters", metrics,
    )

    binding_by_test = {row.get("test_id"): row for row in package.get("trace_bindings") or []}
    trace_ok = len(binding_by_test) == 20
    if trace_ok:
        for criterion in criteria:
            binding = binding_by_test.get(criterion.get("test_id")) or {}
            if binding.get("requirement_id") != criterion.get("requirement_id") or not binding.get("evidence_ids") or any(eid not in evidence_ids for eid in binding.get("evidence_ids") or []):
                trace_ok = False
                break
    checks["CAE-T019"] = (trace_ok, "Requirement→Test→Proof/Evidence trace complete", {"binding_count": len(binding_by_test)})

    signature_state = package.get("signature_state")
    statement_ok = package.get("certification_claim") is False and package.get("statement_type") == "CONFORMITY_EVALUATION_STATEMENT" and signature_state in {"UNSIGNED", "SIGNED_VERIFIED", "SIGNED_UNVERIFIED"}
    if signature_state == "UNSIGNED":
        statement_ok = statement_ok and not package.get("signature")
    checks["CAE-T020"] = (statement_ok, "conformity statement truthful and certification_claim=false", {"signature_state": signature_state})

    results = [ConformanceResult(test_id, "PASS" if checks[test_id][0] else "FAIL", checks[test_id][1], checks[test_id][2]) for test_id in TEST_IDS]
    lifecycle = "REVOKED" if revoked else "SUPERSEDED" if superseded else "EXPIRED" if expired else "REEVALUATION_REQUIRED" if material_drift else "VALID"
    overall = "FAIL" if any(row.result == "FAIL" for row in results) else "BLOCKED" if any(row.result == "BLOCKED" for row in results) else input_decision
    trace = {"schema_version": "1.0", "assessment_id": package.get("assessment_id"), "bindings": package.get("trace_bindings") or [], "evidence_refs": evidence_refs}
    reevaluation = {"schema_version": "1.0", "state": expected_reeval, "triggers": triggers, "lifecycle_state": lifecycle}
    return AssessmentRun(package_dir, package, results, metrics, lifecycle, overall, trace, reevaluation)
