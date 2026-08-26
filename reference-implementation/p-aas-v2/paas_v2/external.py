from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Protocol


class CapabilityStatus(str, Enum):
    SUPPORTED_VERIFIED = "SUPPORTED_VERIFIED"
    SUPPORTED_NOT_VERIFIED = "SUPPORTED_NOT_VERIFIED"
    UNSUPPORTED_WITH_EVIDENCE = "UNSUPPORTED_WITH_EVIDENCE"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    profile_test_ids: list[str]
    advertised: bool
    verified: bool
    status: CapabilityStatus
    source: str
    observed_endpoint: str | None
    http_status: int | None
    reason: str
    artifact_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass(frozen=True)
class AdapterResponse:
    status: int
    payload: Any
    body_text: str
    endpoint: str


@dataclass(frozen=True)
class ImportResult:
    success: bool
    route: str
    responses: list[dict[str, Any]]
    reason: str = ""


class ExternalAASAdapter(Protocol):
    target_metadata: dict[str, Any]
    def health(self) -> AdapterResponse: ...
    def fetch_openapi(self) -> AdapterResponse: ...
    def discover_capabilities(self) -> list[CapabilityRecord]: ...
    def import_environment(self, environment: dict[str, Any]) -> ImportResult: ...
    def read_aas(self, aas_id: str) -> AdapterResponse: ...
    def read_submodel(self, submodel_id: str) -> AdapterResponse: ...
    def read_concept_description(self, cd_id: str) -> AdapterResponse: ...
