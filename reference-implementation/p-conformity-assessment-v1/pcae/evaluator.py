from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_IDS = [f"CAE-T{i:03d}" for i in range(1, 21)]
LEVEL_ORDER = {"C0": 0, "C1": 1, "C2": 2, "C3": 3}
ROLE_BY_LEVEL = {"C0": "SUPPLIER_DECLARANT", "C1": "LAB_EVALUATOR", "C2": "FAT_SAT_EVALUATOR", "C3": "OPERATIONS_MONITOR"}
PROOF_TYPES = {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE", "ATTESTATION", "EXCEPTION_RECORD"}
DIRECT_PROOF_TYPES = ("MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE")
REQUIRED_PROOFS = {
    "C0": {"MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"},
    "C1": {"AUTOMATED_TEST", "LAB_REPORT", "ATTESTATION"},
    "C2": {"FAT_SAT_EVIDENCE", "ATTESTATION"},
    "C3": {"FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE", "ATTESTATION"},
}
MATERIAL_BASELINE_KEYS = (
    "profile_version", "program_version", "parameter_hash", "interface_version",
    "p0_02_status_blob_sha", "p0_06_status_blob_sha",
)
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_profile() -> dict[str, Any]:
    return json.loads((_repo_root() / "machine-readable" / "p0-08" / "automotive-profile-v1.json").read_text(encoding="utf-8"))


def _load_package_schema() -> dict[str, Any]:
    return json.loads((_repo_root() / "machine-readable" / "p0-08" / "conformity-assessment-v1.schema.json").read_text(encoding="utf-8"))


def _schema_valid(value: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> bool:
    root = schema if root is None else root
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return False
        target: Any = root
        try:
            for token in ref[2:].split("/"):
                target = target[token.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            return False
        return isinstance(target, dict) and _schema_valid(value, target, root)

    expected_type = schema.get("type")
    allowed_types = expected_type if isinstance(expected_type, list) else [expected_type] if expected_type else []
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if allowed_types and not any(name in type_checks and type_checks[name](value) for name in allowed_types):
        return False
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        return False

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        if not all(name in value for name in schema.get("required") or []):
            return False
        if schema.get("additionalProperties") is False and any(name not in properties for name in value):
            return False
        if any(name in properties and not _schema_valid(item, properties[name], root) for name, item in value.items()):
            return False
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or ("maxItems" in schema and len(value) > schema["maxItems"]):
            return False
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and any(not _schema_valid(item, item_schema, root) for item in value):
            return False
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
        if schema.get("format") == "date-time":
            try:
                _parse_utc(value)
            except Exception:
                return False
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    return True


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    payload = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def _canonical_sha256(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _upstream_anchor(standard_id: str) -> dict[str, Any] | None:
    try:
        row = next(
            item for item in (_load_profile().get("upstream_sources") or [])
            if item.get("standard_id") == standard_id
        )
        status_path = row.get("status_path")
        expected_blob_sha = row.get("status_blob_sha")
        if not isinstance(status_path, str) or not isinstance(expected_blob_sha, str):
            return None
        repo = _repo_root().resolve()
        source = (repo / status_path).resolve(strict=True)
        source.relative_to(repo)
        if source.is_symlink() or _git_blob_sha(source) != expected_blob_sha:
            return None
        return row
    except Exception:
        return None


def _upstream_status(standard_id: str) -> dict[str, Any] | None:
    anchor = _upstream_anchor(standard_id)
    if not anchor:
        return None
    try:
        value = json.loads((_repo_root() / anchor["status_path"]).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _evidence_map(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("evidence_id")): row for row in package.get("evidence_refs") or [] if row.get("evidence_id")}


def _proof_types(package: dict[str, Any]) -> set[str]:
    return {str(row.get("proof_type")) for row in package.get("evidence_refs") or []}


def _criterion_applies(rule: Any, level: Any) -> bool:
    level_index = LEVEL_ORDER.get(str(level), -1)
    return (
        rule == "ALL"
        or (rule == "C0_RULE" and level == "C0")
        or (rule == "LEVEL_GTE_C1" and level_index >= 1)
        or (rule == "LEVEL_GTE_C2" and level_index >= 2)
        or (rule == "C3" and level == "C3")
    )


def _ref_valid(package_dir: Path, ref: dict[str, Any]) -> bool:
    uri = ref.get("uri")
    safe = isinstance(uri, str) and uri and "://" not in uri and not uri.startswith("/") and ".." not in Path(uri).parts
    if not safe or ref.get("media_type") != "application/json":
        return False
    try:
        root = package_dir.resolve(strict=True)
        path = root
        for part in Path(uri).parts:
            path = path / part
            if path.is_symlink():
                return False
        path = path.resolve(strict=True)
        path.relative_to(root)
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


def _direct_ref_proof(package_dir: Path, package: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any] | None:
    proof_type = ref.get("proof_type")
    if ref.get("source_stage") or proof_type not in DIRECT_PROOF_TYPES:
        return None
    profile = package.get("profile") or {}
    project = package.get("project_binding") or {}
    monitoring = package.get("continuous_monitoring") or {}
    assessment_object = package.get("assessment_object") or {}
    proof = _json_proof(package_dir, ref)
    if (
        not proof or proof.get("kind") != proof_type
        or proof.get("assessment_object_id") != assessment_object.get("object_id")
        or proof.get("assessment_object_type") != assessment_object.get("object_type")
        or proof.get("baseline_sha256") != _canonical_sha256(package.get("baseline") or {})
    ):
        return None
    if proof_type == "MODEL" and proof.get("machine_readable") is True and bool(proof.get("model_id")):
        return proof
    if proof_type == "PROFILE_DECLARATION" and proof.get("profile_id") == profile.get("id") and proof.get("profile_version") == profile.get("version"):
        return proof
    if proof_type == "AUTOMATED_TEST" and proof.get("result") == "PASS" and proof.get("execution_mode") == "AUTOMATED" and ref.get("execution_mode") == "AUTOMATED":
        return proof
    if proof_type == "LAB_REPORT" and proof.get("result") == "PASS" and proof.get("tck") == "P-CAE-TCK-1.0" and bool(proof.get("lab_id")):
        return proof
    if proof_type == "FAT_SAT_EVIDENCE" and proof.get("fat") == proof.get("sat") == "PASS" and proof.get("project_id") == project.get("project_id") and proof.get("instance_id") == project.get("instance_id"):
        return proof
    if (
        proof_type == "CONTINUOUS_EVIDENCE"
        and proof.get("coverage_ratio") == monitoring.get("coverage_ratio") == 1.0
        and proof.get("window_start") == monitoring.get("window_start")
        and proof.get("window_end") == monitoring.get("window_end")
        and isinstance(proof.get("material_open_drifts"), int)
        and not isinstance(proof.get("material_open_drifts"), bool)
        and proof.get("material_open_drifts") >= 0
    ):
        return proof
    return None


def _direct_proof(package_dir: Path, package: dict[str, Any], proof_type: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for ref in package.get("evidence_refs") or []:
        if ref.get("proof_type") == proof_type:
            proof = _direct_ref_proof(package_dir, package, ref)
            if proof:
                return ref, proof
    return None


def _direct_proof_valid(package_dir: Path, package: dict[str, Any], proof_type: str) -> bool:
    return _direct_proof(package_dir, package, proof_type) is not None


def _all_direct_proofs_valid(package_dir: Path, package: dict[str, Any]) -> bool:
    direct_refs = [
        ref for ref in package.get("evidence_refs") or []
        if not ref.get("source_stage") and ref.get("proof_type") in DIRECT_PROOF_TYPES
    ]
    return bool(direct_refs) and all(_direct_ref_proof(package_dir, package, ref) is not None for ref in direct_refs)


def _upstream_proof(package_dir: Path, package: dict[str, Any], standard_id: str) -> dict[str, Any] | None:
    stage, baseline_field = UPSTREAM[standard_id]
    baseline = package.get("baseline") or {}
    anchor = _upstream_anchor(standard_id)
    status = _upstream_status(standard_id)
    if not anchor or not status or baseline.get(baseline_field) != anchor.get("status_blob_sha"):
        return None
    for ref in package.get("evidence_refs") or []:
        if ref.get("source_stage") != stage:
            continue
        proof = _json_proof(package_dir, ref)
        if not proof:
            continue
        summary_valid = True
        if standard_id == "P0-02":
            targets = status.get("targets") or []
            summary_valid = (
                isinstance(targets, list)
                and proof.get("total_implementations") == len(targets)
                and proof.get("verified_implementations") == sum(
                    1 for target in targets if isinstance(target, dict) and target.get("required_failures") == 0
                )
            )
        elif standard_id == "P0-06":
            summary_valid = (
                proof.get("golden_packages") == len(status.get("golden_packages") or {})
                and proof.get("negative_false_pass_count") == (status.get("negative_test_kit") or {}).get("false_pass_count")
                and proof.get("independent_verifier") == (status.get("cross_implementation") or {}).get("independent_node_verifier")
            )
        if (
            proof.get("standard_id") == standard_id
            and proof.get("source_stage") == stage
            and proof.get("status") == "PASS"
            and proof.get("required_failures") == 0
            and proof.get("source_path") == anchor.get("status_path")
            and proof.get("source_blob_sha") == anchor.get("status_blob_sha")
            and proof.get("certification_claim") is False
            and summary_valid
        ):
            return proof
    return None


def _chain_valid(package_dir: Path, package: dict[str, Any], level: str, assessment_time: datetime) -> bool:
    refs = _evidence_map(package)
    assessment_object = package.get("assessment_object") or {}
    profile = package.get("profile") or {}
    baseline_sha256 = _canonical_sha256(package.get("baseline") or {})
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
            and proof.get("assessment_object_id") == assessment_object.get("object_id")
            and proof.get("assessment_object_type") == assessment_object.get("object_type")
            and proof.get("profile_id") == profile.get("id")
            and proof.get("profile_version") == profile.get("version")
            and proof.get("baseline_sha256") == baseline_sha256
            and proof.get("certification_claim") is False
        )
    return False


def _metric_vector(
    package_dir: Path, package: dict[str, Any], criteria: list[dict[str, Any]],
    evidence_ids: set[str], valid_evidence_ids: set[str], required_outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    sources = package.get("effectiveness_sources") or {}
    expected_automatable = sum(
        1 for row in criteria if row.get("required") is True and row.get("automation_flag") is True
    )
    out: dict[str, Any] = {}
    pass_count = sum(1 for row in required_outcomes if row.get("result") == "PASS")
    profile_proofs = set(_load_profile().get("proof_types") or [])
    p002 = _upstream_proof(package_dir, package, "P0-02")
    p002_status = _upstream_status("P0-02") if p002 else None
    direct = {
        proof_type: _direct_proof(package_dir, package, proof_type)
        for proof_type in ("MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE")
    }
    semantic_ids = {
        str(pair[0].get("evidence_id")) for pair in direct.values() if pair and pair[0].get("evidence_id")
    }
    p002_ids = {
        str(ref.get("evidence_id")) for ref in package.get("evidence_refs") or []
        if p002 is not None and ref.get("source_stage") == UPSTREAM["P0-02"][0] and ref.get("evidence_id")
    }
    semantic_ids.update(p002_ids)
    if _upstream_proof(package_dir, package, "P0-06") is not None:
        semantic_ids.update(
            str(ref.get("evidence_id")) for ref in package.get("evidence_refs") or []
            if ref.get("source_stage") == UPSTREAM["P0-06"][0] and ref.get("evidence_id")
        )

    targets = (p002_status.get("targets") or []) if p002_status else []
    cross_d = len(targets)
    cross_n = sum(
        1 for target in targets if isinstance(target, dict) and target.get("required_failures") == 0
    )
    regressions = (p002_status.get("regression") or {}) if p002_status else {}
    regression_signals = (
        p002_status.get("status") == "PASS" if p002_status else False,
        isinstance(regressions.get("embedded_reference"), str) and regressions["embedded_reference"].endswith("PASS"),
        regressions.get("archive_pipeline") == "PASS",
    ) if p002_status else ()
    regression_n, regression_d = sum(regression_signals), len(regression_signals)
    continuous = direct.get("CONTINUOUS_EVIDENCE")
    if package.get("assessment_level") == "C3" and continuous:
        closed = continuous[1].get("closed_drifts")
        opened = continuous[1].get("material_open_drifts")
        if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (closed, opened)):
            drift_n, drift_d = closed, closed + opened
        else:
            drift_n, drift_d = -1, -1
    else:
        drift_n = drift_d = 0
    expected = {
        "machine_readable_coverage": (len(profile_proofs & PROOF_TYPES), len(PROOF_TYPES)),
        "requirement_testability": (len({row.get("test_id") for row in criteria} & set(TEST_IDS)), len(TEST_IDS)),
        "automation_rate": (expected_automatable, expected_automatable),
        "evidence_completeness": (len(valid_evidence_ids), len(evidence_ids)),
        "applicable_required_pass_rate": (pass_count, len(required_outcomes)),
        "cross_implementation_reproducibility": (cross_n, cross_d),
        "regression_stability": (regression_n, regression_d),
        "c3_drift_closure_rate": (drift_n, drift_d),
    }
    for name in METRIC_NAMES:
        row = sources.get(name) or {}
        numerator, denominator = row.get("numerator"), row.get("denominator")
        refs = row.get("source_evidence_ids")
        valid = (
            isinstance(numerator, int) and isinstance(denominator, int)
            and not isinstance(numerator, bool) and not isinstance(denominator, bool)
            and numerator >= 0 and denominator >= 0 and numerator <= denominator
            and (numerator, denominator) == expected[name]
            and isinstance(refs, list) and bool(refs) and len(refs) == len(set(refs))
            and set(refs).issubset(valid_evidence_ids)
            and (name == "evidence_completeness" or set(refs).issubset(semantic_ids))
        )
        if name == "evidence_completeness":
            valid = valid and set(refs) == evidence_ids
        elif name in {"cross_implementation_reproducibility", "regression_stability"} and p002 is not None:
            valid = valid and set(refs).issubset(p002_ids)
        elif name == "c3_drift_closure_rate" and package.get("assessment_level") == "C3":
            valid = valid and continuous is not None and continuous[0].get("evidence_id") in refs
        if not valid:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "INVALID", "value": None}
        elif denominator == 0:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "NOT_APPLICABLE", "value": None}
        else:
            out[name] = {"numerator": numerator, "denominator": denominator, "source_evidence_ids": refs, "status": "MEASURED", "value": numerator / denominator}
    return out


def _runtime_shape_safe(package: Any) -> bool:
    if not isinstance(package, dict):
        return False
    object_fields = (
        "profile", "criteria_registry", "assessor", "assessment_object", "baseline",
        "observed_baseline", "execution_summary", "effectiveness_sources",
        "claimed_effectiveness_metrics", "validity", "statement_scope",
    )
    list_fields = (
        "evidence_refs", "not_applicable", "exceptions", "assurance_chain",
        "required_outcomes", "drifts", "trace_bindings",
    )
    if any(not isinstance(package.get(name), dict) for name in object_fields):
        return False
    if any(
        not isinstance(package.get(name), list)
        or any(not isinstance(row, dict) for row in package[name])
        for name in list_fields
    ):
        return False
    for optional in ("project_binding", "continuous_monitoring", "signature"):
        if optional in package and not isinstance(package[optional], dict):
            return False
    return all(
        isinstance((package.get(section) or {}).get(name), dict)
        for section in ("effectiveness_sources", "claimed_effectiveness_metrics")
        for name in METRIC_NAMES
    )


def _invalid_shape_run(package_dir: Path) -> AssessmentRun:
    results = [ConformanceResult("CAE-T001", "FAIL", "package does not conform to the published runtime schema")]
    results.extend(
        ConformanceResult(test_id, "BLOCKED", "package shape invalid") for test_id in TEST_IDS[1:]
    )
    safe_package = {
        "assessment_time": "1970-01-01T00:00:00Z",
        "assessment_level": "C0",
        "assessment_object": {},
        "signature_state": "UNSIGNED",
    }
    return AssessmentRun(
        package_dir, safe_package, results, {}, "REEVALUATION_REQUIRED", "FAIL",
        {"schema_version": "1.0", "bindings": [], "evidence_refs": []},
        {"schema_version": "1.0", "state": "REQUIRED", "triggers": ["PACKAGE_SCHEMA_INVALID"], "lifecycle_state": "REEVALUATION_REQUIRED"},
    )


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
    if not _runtime_shape_safe(package):
        return _invalid_shape_run(package_dir)

    cac = _load_cac()
    criteria = cac.get("criteria") or []
    criteria_by_test = {row.get("test_id"): row for row in criteria}
    checks: dict[str, tuple[bool, str, Any]] = {}
    level = package.get("assessment_level")
    level_index = LEVEL_ORDER.get(str(level), -1)
    try:
        schema_valid = _schema_valid(package, _load_package_schema())
    except Exception:
        schema_valid = False
    try:
        assessment_time = _parse_utc(package.get("assessment_time"))
    except Exception:
        assessment_time = datetime.max.replace(tzinfo=timezone.utc)

    checks["CAE-T001"] = (
        schema_valid and package.get("schema_version") == "1.0" and bool(package.get("assessment_id"))
        and (package.get("profile") or {}).get("id") == "P-CAE-AUTO-R14"
        and (package.get("profile") or {}).get("version") == "1.0" and level in LEVEL_ORDER,
        "assessment/package/schema/profile identity complete", {"assessment_id": package.get("assessment_id"), "level": level, "schema_valid": schema_valid},
    )

    required_fields = {"requirement_id", "proof_type", "test_id", "automation_flag", "required", "na_allowed", "applicability_rule", "decision_rule", "evidence_requirements"}
    test_ids = [row.get("test_id") for row in criteria]
    req_ids = [row.get("requirement_id") for row in criteria]
    registry = package.get("criteria_registry") or {}
    registry_valid = (
        registry.get("registry_id") == cac.get("registry_id")
        and registry.get("registry_version") == cac.get("registry_version")
        and registry.get("sha256") == _sha256(_repo_root() / "machine-readable" / "p0-08" / "conformance-criteria-v1.json")
    )
    checks["CAE-T002"] = (
        registry_valid and test_ids == TEST_IDS and len(req_ids) == len(set(req_ids)) == 20 and all(required_fields.issubset(row) for row in criteria),
        "CAC identifiers unique and authoritative registry binding complete", {"criteria_count": len(criteria), "registry_valid": registry_valid},
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
        actual_proofs.issubset(PROOF_TYPES)
        and REQUIRED_PROOFS.get(str(level), set()).issubset(actual_proofs)
        and _all_direct_proofs_valid(package_dir, package),
        "proof types valid, direct proof semantics valid and level-required proof set present", {"proof_types": sorted(actual_proofs)},
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

    required_outcomes = package.get("required_outcomes") or []
    expected_outcome_ids = {
        str(row.get("requirement_id")) for row in criteria if row.get("required") is True
    }
    outcome_ids = [str(row.get("requirement_id")) for row in required_outcomes]
    outcome_registry_ok = (
        len(outcome_ids) == len(expected_outcome_ids)
        and len(outcome_ids) == len(set(outcome_ids))
        and set(outcome_ids) == expected_outcome_ids
        and all(row.get("result") in {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"} for row in required_outcomes)
    )
    outcomes_by_requirement = {str(row.get("requirement_id")): row.get("result") for row in required_outcomes}
    na_records = package.get("not_applicable") or []
    na_by_test = {str(row.get("test_id")): row for row in na_records if row.get("test_id")}
    na_ok = outcome_registry_ok and len(na_by_test) == len(na_records)
    for row in na_records:
        criterion = criteria_by_test.get(row.get("test_id"))
        if (
            not criterion or criterion.get("na_allowed") is not True
            or not bool(row.get("justification"))
            or outcomes_by_requirement.get(str(criterion.get("requirement_id"))) != "NOT_APPLICABLE"
        ):
            na_ok = False
            break
    for criterion in criteria:
        if outcomes_by_requirement.get(str(criterion.get("requirement_id"))) == "NOT_APPLICABLE":
            record = na_by_test.get(str(criterion.get("test_id")))
            if criterion.get("na_allowed") is not True or not record or not bool(record.get("justification")):
                na_ok = False
                break
    checks["CAE-T007"] = (na_ok, "NOT_APPLICABLE permission comes from CAC and requires justification", na_records)

    exceptions = package.get("exceptions") or []
    checks["CAE-T008"] = (all(row.get("masks_required_failure") is not True for row in exceptions), "exceptions do not mask required FAIL/BLOCKED", exceptions)

    checks["CAE-T009"] = (
        level != "C0" or all(
            _direct_proof_valid(package_dir, package, proof_type)
            for proof_type in ("MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST")
        ),
        "C0 supplier-declaration inputs complete when applicable", None,
    )

    p002 = _upstream_proof(package_dir, package, "P0-02")
    p006 = _upstream_proof(package_dir, package, "P0-06")
    c0_chain = _chain_valid(package_dir, package, "C0", assessment_time) if level_index >= 1 else True
    c1_chain = _chain_valid(package_dir, package, "C1", assessment_time) if level_index >= 2 else True
    c2_chain = _chain_valid(package_dir, package, "C2", assessment_time) if level_index >= 3 else True

    if level == "C1":
        c1_ok = c0_chain and _direct_proof_valid(package_dir, package, "LAB_REPORT") and p002 is not None
    elif level_index > 1:
        c1_ok = c0_chain and c1_chain
    else:
        c1_ok = True
    checks["CAE-T010"] = (c1_ok, "C1 proof or inherited hash-bound C1 assessment valid", None)

    if level_index >= 2:
        binding = package.get("project_binding") or {}
        c2_ok = (
            c1_chain and bool(binding.get("project_id")) and bool(binding.get("instance_id"))
            and p006 is not None and _direct_proof_valid(package_dir, package, "FAT_SAT_EVIDENCE")
        )
    else:
        c2_ok = True
    checks["CAE-T011"] = (c2_ok, "C2 predecessor/project binding/authoritative P0-06 proof valid when applicable", None)

    c3_ok = True
    if level == "C3":
        monitoring = package.get("continuous_monitoring") or {}
        try:
            start, end = _parse_utc(monitoring.get("window_start")), _parse_utc(monitoring.get("window_end"))
            coverage_days = (end - start).total_seconds() / 86400
            required_days = monitoring.get("required_days")
            c3_ok = (
                c2_chain and isinstance(required_days, int) and not isinstance(required_days, bool)
                and required_days >= 1 and end > start
                and monitoring.get("coverage_ratio") == 1.0
                and coverage_days >= required_days
                and _direct_proof_valid(package_dir, package, "CONTINUOUS_EVIDENCE")
            )
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

    continuous_pair = _direct_proof(package_dir, package, "CONTINUOUS_EVIDENCE")
    continuous_material_open = continuous_pair[1].get("material_open_drifts", 0) if continuous_pair else 0
    material_drift = (
        any(baseline.get(key) != observed.get(key) for key in MATERIAL_BASELINE_KEYS)
        or any(row.get("material") is True and row.get("status") != "CLOSED" for row in package.get("drifts") or [])
        or continuous_material_open > 0
    )
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

    outcomes = [row.get("result") for row in required_outcomes]
    applicable_outcomes = [value for value in outcomes if value != "NOT_APPLICABLE"]
    input_decision = (
        "FAIL" if "FAIL" in applicable_outcomes else "BLOCKED" if "BLOCKED" in applicable_outcomes
        else "PASS" if applicable_outcomes else "NOT_APPLICABLE"
    )
    checks["CAE-T017"] = (
        outcome_registry_ok and package.get("declared_decision") == input_decision and "weighted_score" not in package,
        "overall decision deterministic with FAIL>BLOCKED>PASS and no weighted score", {"computed": input_decision},
    )

    metrics = _metric_vector(package_dir, package, criteria, evidence_ids, valid_refs, required_outcomes)
    checks["CAE-T018"] = (
        metrics == (package.get("claimed_effectiveness_metrics") or {}) and all(row.get("status") != "INVALID" for row in metrics.values()),
        "effectiveness vector reproducible from CAC, outcomes and evidence-sourced counters", metrics,
    )

    trace_bindings = package.get("trace_bindings") or []
    binding_by_test = {row.get("test_id"): row for row in trace_bindings}
    direct_by_type: dict[str, set[str]] = {}
    for proof_type in ("MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE"):
        pair = _direct_proof(package_dir, package, proof_type)
        direct_by_type[proof_type] = {str(pair[0].get("evidence_id"))} if pair and pair[0].get("evidence_id") else set()
    semantic_trace_ids = set().union(*direct_by_type.values())
    p002_trace_ids: set[str] = set()
    p006_trace_ids: set[str] = set()
    if p002 is not None:
        p002_trace_ids = {
            str(ref.get("evidence_id")) for ref in evidence_refs
            if ref.get("source_stage") == UPSTREAM["P0-02"][0] and ref.get("evidence_id")
        }
        semantic_trace_ids.update(p002_trace_ids)
    if p006 is not None:
        p006_trace_ids = {
            str(ref.get("evidence_id")) for ref in evidence_refs
            if ref.get("source_stage") == UPSTREAM["P0-06"][0] and ref.get("evidence_id")
        }
        semantic_trace_ids.update(p006_trace_ids)
    chain_ids = {
        chain_level: {
            str(row.get("evidence_id")) for row in package.get("assurance_chain") or []
            if row.get("level") == chain_level and row.get("evidence_id")
        } if _chain_valid(package_dir, package, chain_level, assessment_time) else set()
        for chain_level in ("C0", "C1", "C2")
    }
    token_sources = {
        "MODEL": direct_by_type["MODEL"],
        "PROFILE_DECLARATION": direct_by_type["PROFILE_DECLARATION"],
        "AUTOMATED_TEST": direct_by_type["AUTOMATED_TEST"],
        "LAB_REPORT": direct_by_type["LAB_REPORT"] or chain_ids["C1"],
        "FAT_SAT_EVIDENCE": direct_by_type["FAT_SAT_EVIDENCE"],
        "CONTINUOUS_EVIDENCE": direct_by_type["CONTINUOUS_EVIDENCE"],
        "C0_PREDECESSOR": chain_ids["C0"],
        "C1_PREDECESSOR": chain_ids["C1"],
        "C2_PREDECESSOR": chain_ids["C2"],
        "PROJECT_BINDING": direct_by_type["FAT_SAT_EVIDENCE"],
        "P0_06_EVIDENCE": p006_trace_ids,
    }
    trace_ok = len(trace_bindings) == len(binding_by_test) == 20
    if trace_ok:
        for criterion in criteria:
            binding = binding_by_test.get(criterion.get("test_id")) or {}
            bound_ids = binding.get("evidence_ids") or []
            required_semantic_ids = direct_by_type.get(str(criterion.get("proof_type"))) or semantic_trace_ids
            required_source_sets = [required_semantic_ids]
            if _criterion_applies(criterion.get("applicability_rule"), level):
                required_source_sets.extend(
                    token_sources.get(str(token), semantic_trace_ids)
                    for token in criterion.get("evidence_requirements") or []
                )
            if (
                binding.get("requirement_id") != criterion.get("requirement_id")
                or not bound_ids or len(bound_ids) != len(set(bound_ids))
                or any(eid not in valid_refs for eid in bound_ids)
                or any(not sources or not set(bound_ids).intersection(sources) for sources in required_source_sets)
            ):
                trace_ok = False
                break
    checks["CAE-T019"] = (trace_ok, "Requirement→Test→Proof/Evidence trace complete", {"binding_count": len(binding_by_test)})

    signature_state = package.get("signature_state")
    scope = package.get("statement_scope") or {}
    statement_ok = (
        package.get("certification_claim") is False
        and package.get("statement_type") == "CONFORMITY_EVALUATION_STATEMENT"
        and scope.get("assessment_object_id") == (package.get("assessment_object") or {}).get("object_id")
        and scope.get("assessment_level") == level
        and scope.get("profile_id") == (package.get("profile") or {}).get("id")
        and scope.get("profile_version") == (package.get("profile") or {}).get("version")
        and signature_state == "UNSIGNED" and not package.get("signature")
    )
    checks["CAE-T020"] = (statement_ok, "conformity statement truthful and certification_claim=false", {"signature_state": signature_state})

    inconsistent_outcomes = [
        str(criterion.get("requirement_id"))
        for criterion in criteria
        if criterion.get("test_id") != "CAE-T017"
        and (
            outcomes_by_requirement.get(str(criterion.get("requirement_id"))) == "PASS"
        ) != bool(checks.get(str(criterion.get("test_id")), (False, "", None))[0])
    ]
    decision_ok, decision_reason, decision_observations = checks["CAE-T017"]
    checks["CAE-T017"] = (
        decision_ok and not inconsistent_outcomes,
        decision_reason + "; required outcomes reconcile with observed conformance evidence",
        {**decision_observations, "inconsistent_requirement_ids": inconsistent_outcomes},
    )

    results = [ConformanceResult(test_id, "PASS" if checks[test_id][0] else "FAIL", checks[test_id][1], checks[test_id][2]) for test_id in TEST_IDS]
    lifecycle = "REVOKED" if revoked else "SUPERSEDED" if superseded else "EXPIRED" if expired else "REEVALUATION_REQUIRED" if material_drift else "VALID"
    overall = "FAIL" if any(row.result == "FAIL" for row in results) else "BLOCKED" if any(row.result == "BLOCKED" for row in results) else input_decision
    trace = {"schema_version": "1.0", "assessment_id": package.get("assessment_id"), "bindings": package.get("trace_bindings") or [], "evidence_refs": evidence_refs}
    reevaluation = {"schema_version": "1.0", "state": expected_reeval, "triggers": triggers, "lifecycle_state": lifecycle}
    return AssessmentRun(package_dir, package, results, metrics, lifecycle, overall, trace, reevaluation)
