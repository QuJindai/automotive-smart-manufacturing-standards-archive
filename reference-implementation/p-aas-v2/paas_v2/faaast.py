from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from .external import AdapterResponse, CapabilityRecord, CapabilityStatus, ImportResult
from .http import HttpEvidence, TransportBlocked, encode_identifier, request


class FaaastAdapter:
    def __init__(self, base_url: str, target_metadata: dict[str, Any] | None = None):
        self.base_url = base_url.rstrip("/")
        self.target_metadata = dict(target_metadata or {})
        self.target_metadata.setdefault("implementation", "Fraunhofer IOSB FA3ST Service")
        self.api_prefix = str(self.target_metadata.get("api_prefix", "/api/v3.0")).rstrip("/")

    def _url(self, path: str) -> str:
        return self.base_url + self.api_prefix + path

    @staticmethod
    def _response(ev: HttpEvidence) -> AdapterResponse:
        return AdapterResponse(ev.status, ev.json_body, ev.body_text, ev.url)

    def health(self) -> AdapterResponse:
        ev = request("GET", self._url("/shells?limit=1"), headers={"Accept": "application/json"}, timeout=5)
        payload = {
            "probe": "aas-repository",
            "endpoint": ev.url,
            "status": ev.status,
            "implementation": self.target_metadata.get("implementation"),
            "version": self.target_metadata.get("version", "unknown"),
        }
        return AdapterResponse(ev.status, payload, ev.body_text, ev.url)

    def fetch_openapi(self) -> AdapterResponse:
        return self.health()

    def _probe(self, path: str) -> int | None:
        try:
            return request("GET", self._url(path), headers={"Accept": "application/json"}, timeout=3).status
        except TransportBlocked:
            return None

    def discover_capabilities(self) -> list[CapabilityRecord]:
        specs = [
            ("read_aas", ["AAS-T011"], "/shells?limit=1", "/shells/{aasIdentifier}"),
            ("read_submodel", ["AAS-T012"], "/submodels?limit=1", "/submodels/{submodelIdentifier}"),
            ("read_concept_description", ["AAS-T004", "AAS-T005", "AAS-T006", "AAS-T007", "AAS-T008"], "/concept-descriptions?limit=1", "/concept-descriptions/{cdIdentifier}"),
        ]
        records: list[CapabilityRecord] = []
        for cap, tids, probe, endpoint in specs:
            status = self._probe(probe)
            verified = status == 200
            records.append(
                CapabilityRecord(
                    cap,
                    tids,
                    verified,
                    verified,
                    CapabilityStatus.SUPPORTED_VERIFIED if verified else CapabilityStatus.BLOCKED,
                    "runtime-probe",
                    self.api_prefix + endpoint,
                    status,
                    "FA3ST AAS API v3.0 repository probe returned 200" if verified else "FA3ST repository probe did not return 200",
                    [],
                )
            )

        records.append(CapabilityRecord("environment_import", [], True, False, CapabilityStatus.SUPPORTED_NOT_VERIFIED, "target-profile", self.api_prefix + "/import", None, "FA3ST proprietary import API; verified during fixture import", []))
        records.append(CapabilityRecord("query", ["AAS-T010"], False, False, CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "target-profile", None, None, "AAS Query Language is outside the exercised FA3ST 1.3.0 profile", []))
        records.append(CapabilityRecord("authorization", ["AAS-T013", "AAS-T014", "AAS-T015", "AAS-T016"], False, False, CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "vendor-documentation", None, None, "FA3ST Service 1.3.0 does not implement AAS security mechanisms", []))
        records.append(CapabilityRecord("signed", ["AAS-T017"], False, False, CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "vendor-documentation", None, None, "no signed-response capability in exercised FA3ST profile", []))
        serialization_status = self._probe("/serialization")
        serialization_present = serialization_status in {200, 400, 404, 405}
        records.append(CapabilityRecord("aasx_package", ["AAS-T018", "AAS-T019"], serialization_present, False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if serialization_present else CapabilityStatus.BLOCKED, "runtime-probe", self.api_prefix + "/serialization", serialization_status, "serialization endpoint reachable; package validity verified during execution" if serialization_present else "serialization endpoint probe blocked", []))
        return records

    def import_environment(self, environment: dict[str, Any]) -> ImportResult:
        payload = json.dumps(environment, ensure_ascii=False).encode("utf-8")
        try:
            ev = request(
                "POST",
                self._url("/import"),
                payload,
                {"Content-Type": "application/json", "Accept": "application/json"},
                timeout=15,
            )
        except TransportBlocked as exc:
            return ImportResult(False, "none", [], str(exc))
        response = {"route": self.api_prefix + "/import", "status": ev.status, "body": ev.body_text[:1000]}
        if 200 <= ev.status < 300:
            return ImportResult(True, "faaast-import-json", [response])
        return ImportResult(False, "faaast-import-json", [response], f"FA3ST import failed with HTTP {ev.status}")

    def read_aas(self, aas_id: str) -> AdapterResponse:
        return self._response(request("GET", self._url(f"/shells/{encode_identifier(aas_id)}"), headers={"Accept": "application/json"}))

    def read_submodel(self, submodel_id: str) -> AdapterResponse:
        return self._response(request("GET", self._url(f"/submodels/{encode_identifier(submodel_id)}"), headers={"Accept": "application/json"}))

    def read_concept_description(self, cd_id: str) -> AdapterResponse:
        return self._response(request("GET", self._url(f"/concept-descriptions/{encode_identifier(cd_id)}"), headers={"Accept": "application/json"}))

    def serialize_aasx(self, aas_ids: list[str], submodel_ids: list[str], include_concept_descriptions: bool = True) -> HttpEvidence:
        params: list[tuple[str, str]] = []
        params.extend(("aasIds", encode_identifier(value)) for value in aas_ids)
        params.extend(("submodelIds", encode_identifier(value)) for value in submodel_ids)
        params.append(("includeConceptDescriptions", "true" if include_concept_descriptions else "false"))
        url = self._url("/serialization") + "?" + urlencode(params, doseq=True)
        return request("GET", url, headers={"Accept": "application/asset-administration-shell-package+xml"}, timeout=15)
