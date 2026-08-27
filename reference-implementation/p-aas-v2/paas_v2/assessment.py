from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from .external import CapabilityRecord, CapabilityStatus


@dataclass(frozen=True)
class AssessmentResult:
    test_id: str
    result: str
    capability_status: str
    reason: str
    assertions: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_optional(test_id: str, capability: CapabilityRecord) -> AssessmentResult:
    if capability.status == CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE:
        return AssessmentResult(test_id, "NOT_APPLICABLE", capability.status.value, capability.reason, [{"assertion_id":"capability","status":"NOT_APPLICABLE","expected":"optional capability if implemented","observed":capability.reason,"message":None}], [])
    if capability.status in {CapabilityStatus.BLOCKED, CapabilityStatus.UNKNOWN, CapabilityStatus.SUPPORTED_NOT_VERIFIED}:
        return AssessmentResult(test_id, "BLOCKED", capability.status.value, capability.reason, [], [])
    return AssessmentResult(test_id, "PASS", capability.status.value, capability.reason, [], [])


def external_result(test_id: str, capability: CapabilityRecord, required: bool, passed: bool | None = None, reason: str | None = None, assertions: list[dict[str, Any]] | None = None) -> AssessmentResult:
    if capability.status in {CapabilityStatus.BLOCKED, CapabilityStatus.UNKNOWN}:
        return AssessmentResult(test_id, "BLOCKED", capability.status.value, reason or capability.reason, assertions or [], [])
    if capability.status == CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE:
        return AssessmentResult(test_id, "FAIL" if required else "NOT_APPLICABLE", capability.status.value, reason or capability.reason, assertions or [], [])
    if passed is False:
        return AssessmentResult(test_id, "FAIL", capability.status.value, reason or "verification failed", assertions or [], [])
    return AssessmentResult(test_id, "PASS", capability.status.value, reason or "verified", assertions or [], [])
