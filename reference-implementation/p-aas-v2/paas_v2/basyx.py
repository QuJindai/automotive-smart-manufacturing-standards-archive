from __future__ import annotations

import base64
import json
import secrets
from typing import Any
from urllib.parse import urlencode

from .external import AdapterResponse, CapabilityRecord, CapabilityStatus, ImportResult
from .http import HttpEvidence, TransportBlocked, encode_identifier, request


class BasyxAdapter:
    def __init__(self, base_url: str, target_metadata: dict[str, Any] | None = None):
        self.base_url = base_url.rstrip("/")
        self.target_metadata = dict(target_metadata or {})
        self.target_metadata.setdefault("implementation", "Eclipse BaSyx")
        self._openapi: dict[str, Any] | None = None

    def _response(self, ev: HttpEvidence) -> AdapterResponse:
        return AdapterResponse(ev.status, ev.json_body, ev.body_text, ev.url)

    def health(self) -> AdapterResponse:
        return self.fetch_openapi()

    @staticmethod
    def _normalize_openapi_payload(payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            return payload
        if not isinstance(payload, str) or not payload:
            return None
        try:
            padded = payload + "=" * ((4 - len(payload) % 4) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
            candidate = json.loads(decoded)
            return candidate if isinstance(candidate, dict) else None
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def fetch_openapi(self) -> AdapterResponse:
        ev = request("GET", self.base_url + "/v3/api-docs")
        normalized = self._normalize_openapi_payload(ev.json_body)
        if ev.status == 200 and normalized is not None:
            self._openapi = normalized
            return AdapterResponse(ev.status, normalized, ev.body_text, ev.url)
        return self._response(ev)

    def _paths(self) -> dict[str, Any]:
        if self._openapi is None:
            r = self.fetch_openapi()
            if r.status != 200 or not isinstance(r.payload, dict):
                raise TransportBlocked("OpenAPI unavailable")
        return dict(self._openapi.get("paths") or {})

    def _probe_path(self, prefix: str) -> int | None:
        try:
            ev = request("GET", self.base_url + prefix + "/" + encode_identifier("urn:example:probe:missing"), timeout=3)
            return ev.status
        except TransportBlocked:
            return None

    def discover_capabilities(self) -> list[CapabilityRecord]:
        try:
            paths = self._paths()
        except TransportBlocked as exc:
            return [CapabilityRecord("openapi", [], False, False, CapabilityStatus.BLOCKED, "transport", "/v3/api-docs", None, str(exc), [])]

        def path_contains(fragment: str) -> str | None:
            for p in paths:
                if fragment in p:
                    return p
            return None

        records: list[CapabilityRecord] = []
        specs = [
            ("read_aas", ["AAS-T011"], "/shells/{", "/shells"),
            ("read_submodel", ["AAS-T012"], "/submodels/{", "/submodels"),
            ("read_concept_description", ["AAS-T004","AAS-T005","AAS-T006","AAS-T007","AAS-T008"], "/concept-descriptions/{", "/concept-descriptions"),
        ]
        for cap, tids, frag, probe in specs:
            p = path_contains(frag)
            if p:
                status = self._probe_path(probe)
                verified = status in {200, 400, 404}
                records.append(CapabilityRecord(cap, tids, True, verified, CapabilityStatus.SUPPORTED_VERIFIED if verified else CapabilityStatus.SUPPORTED_NOT_VERIFIED, "openapi+probe", p, status, "advertised in OpenAPI" if verified else "advertised; probe blocked", []))
            else:
                records.append(CapabilityRecord(cap, tids, False, False, CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "openapi", None, None, "endpoint absent from OpenAPI", []))

        upload = path_contains("/upload")
        records.append(CapabilityRecord("environment_import", [], bool(upload), False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if upload else CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "openapi", upload, None, "BaSyx environment upload" if upload else "upload endpoint absent", []))
        query_paths = [p for p in paths if "query" in p.lower() or "search" in p.lower()]
        records.append(CapabilityRecord("query", ["AAS-T010"], bool(query_paths), False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if query_paths else CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "openapi", query_paths[0] if query_paths else None, None, "query/search path advertised" if query_paths else "query/search endpoint absent from OpenAPI", []))
        auth_enabled = bool(self.target_metadata.get("authorization_enabled", False))
        records.append(CapabilityRecord("authorization", ["AAS-T013","AAS-T014","AAS-T015","AAS-T016"], auth_enabled, False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if auth_enabled else CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "target-config", None, None, "authorization configured" if auth_enabled else "authorization disabled in target profile", []))
        signed = [p for p in paths if "signed" in p.lower()]
        records.append(CapabilityRecord("signed", ["AAS-T017"], bool(signed), False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if signed else CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "openapi", signed[0] if signed else None, None, "signed endpoint advertised" if signed else "signed endpoint absent from OpenAPI", []))
        aasx = [p for p in paths if "aasx" in p.lower() or "package" in p.lower() or "serialization" in p.lower()]
        records.append(CapabilityRecord("aasx_package", ["AAS-T018","AAS-T019"], bool(aasx), False, CapabilityStatus.SUPPORTED_NOT_VERIFIED if aasx else CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE, "openapi", aasx[0] if aasx else None, None, "AASX/package/serialization path advertised" if aasx else "AASX/package export endpoint absent from OpenAPI", []))
        return records

    def _multipart(self, filename: str, payload: bytes, mime: str) -> tuple[bytes, str]:
        boundary = "----PAASV2" + secrets.token_hex(8)
        body = (f"--{boundary}\r\n" f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n" f"Content-Type: {mime}\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        return body, boundary

    def import_environment(self, environment: dict[str, Any]) -> ImportResult:
        responses: list[dict[str, Any]] = []
        try:
            paths = self._paths()
        except TransportBlocked as exc:
            return ImportResult(False, "none", [], str(exc))
        if "/upload" in paths:
            body, boundary = self._multipart("environment.json", json.dumps(environment, ensure_ascii=False).encode("utf-8"), "application/json")
            ev = request("POST", self.base_url + "/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
            responses.append({"route":"/upload","status":ev.status,"body":ev.body_text[:1000]})
            if 200 <= ev.status < 300:
                return ImportResult(True, "upload-json", responses)

        route_specs = [("conceptDescriptions", "/concept-descriptions"), ("submodels", "/submodels"), ("assetAdministrationShells", "/shells")]
        ok = True
        for key, path in route_specs:
            for obj in environment.get(key, []):
                ev = request("POST", self.base_url + path, obj, {"Accept":"application/json"})
                responses.append({"route":path,"id":obj.get("id"),"status":ev.status,"body":ev.body_text[:1000]})
                if ev.status not in {200, 201, 204, 409}:
                    ok = False
        return ImportResult(ok, "repository-posts", responses, "" if ok else "one or more repository POSTs failed")

    def read_aas(self, aas_id: str) -> AdapterResponse:
        return self._response(request("GET", f"{self.base_url}/shells/{encode_identifier(aas_id)}", headers={"Accept":"application/json"}))

    def read_submodel(self, submodel_id: str) -> AdapterResponse:
        return self._response(request("GET", f"{self.base_url}/submodels/{encode_identifier(submodel_id)}", headers={"Accept":"application/json"}))

    def read_concept_description(self, cd_id: str) -> AdapterResponse:
        return self._response(request("GET", f"{self.base_url}/concept-descriptions/{encode_identifier(cd_id)}", headers={"Accept":"application/json"}))

    def serialize_aasx(self, aas_ids: list[str], submodel_ids: list[str], include_concept_descriptions: bool = True) -> HttpEvidence:
        params: list[tuple[str, str]] = []
        params.extend(("aasIds", encode_identifier(value)) for value in aas_ids)
        params.extend(("submodelIds", encode_identifier(value)) for value in submodel_ids)
        params.append(("includeConceptDescriptions", "true" if include_concept_descriptions else "false"))
        url = self.base_url + "/serialization?" + urlencode(params, doseq=True)
        return request("GET", url, headers={"Accept":"application/asset-administration-shell-package+xml"})
