from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paas_ref.aasx import validate_aasx
from .assessment import AssessmentResult, classify_optional, external_result
from .external import CapabilityRecord, CapabilityStatus, ExternalAASAdapter
from .http import TransportBlocked
from .output import write_outputs
from .v1_bridge import normalize_bundle, run_core_semantic_checks

CHECK_TO_TEST={"asset-kind":"AAS-T002","asset-identifier":"AAS-T003","required-semantics":"AAS-T004","iec61360":"AAS-T005","preferred-languages":"AAS-T006","unit-consistency":"AAS-T007","unit-resolvability":"AAS-T008"}
CORE_CAPS={"read_aas":"AAS-T011","read_submodel":"AAS-T012"}
OPTIONAL={"query":["AAS-T010"],"authorization":["AAS-T013","AAS-T014","AAS-T015","AAS-T016"],"signed":["AAS-T017"]}


def _cap_map(capabilities: list[CapabilityRecord]) -> dict[str, CapabilityRecord]:
    return {c.capability_id:c for c in capabilities}


def _promote(capabilities: list[CapabilityRecord], capability_id: str, reason: str, http_status: int | None = None, endpoint: str | None = None, artifact_refs: list[str] | None = None) -> list[CapabilityRecord]:
    promoted=[]
    for c in capabilities:
        if c.capability_id == capability_id:
            promoted.append(replace(c, advertised=True, verified=True, status=CapabilityStatus.SUPPORTED_VERIFIED, source=c.source+"+runtime", observed_endpoint=endpoint or c.observed_endpoint, http_status=http_status if http_status is not None else c.http_status, reason=reason, artifact_refs=list(artifact_refs or c.artifact_refs)))
        else:
            promoted.append(c)
    return promoted


def _assertion(check) -> list[dict[str, Any]]:
    return [{"assertion_id":check.check_id,"status":"PASS" if check.passed else "FAIL","expected":"P-AAS V1 rule satisfied","observed":check.observed,"message":check.message}]


def _artifact(path: Path, artifact_id: str, mime_type: str) -> dict[str, Any]:
    return {"artifact_id":artifact_id,"name":path.name,"uri":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"mime_type":mime_type,"created_at":datetime.now(timezone.utc).isoformat(),"source_system":"p-aas-v2"}


def _supplementary_refs(fixture: dict[str, Any]) -> set[str]:
    refs=set()
    def walk(elements):
        for e in elements or []:
            if e.get("modelType") == "File" and e.get("value"):
                refs.add(Path(str(e["value"])).name)
            walk(e.get("value") if isinstance(e.get("value"),list) else e.get("submodelElements"))
    for sm in fixture.get("submodels",[]): walk(sm.get("submodelElements"))
    return refs


def run_external(adapter: ExternalAASAdapter, fixture: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    health=adapter.health()
    if health.status != 200: raise RuntimeError(f"external OpenAPI health failed: {health.status}")
    (out_dir/"openapi.json").write_text(json.dumps(health.payload,ensure_ascii=False,indent=2),encoding="utf-8")
    capabilities=adapter.discover_capabilities(); cmap=_cap_map(capabilities)
    imp=adapter.import_environment(fixture)
    (out_dir/"import-response.json").write_text(json.dumps({"success":imp.success,"route":imp.route,"responses":imp.responses,"reason":imp.reason},ensure_ascii=False,indent=2),encoding="utf-8")
    if not imp.success: raise RuntimeError("fixture import failed: "+imp.reason)
    import_status=next((r.get("status") for r in imp.responses if 200 <= int(r.get("status",0)) < 300),None)
    capabilities=_promote(capabilities,"environment_import",f"fixture import verified via {imp.route}",import_status,"/upload" if imp.route=="upload-json" else "repository-posts",["import-response.json"]); cmap=_cap_map(capabilities)

    aas_id=fixture["assetAdministrationShells"][0]["id"]; aas_r=adapter.read_aas(aas_id)
    if aas_r.status != 200 or not isinstance(aas_r.payload,dict): raise RuntimeError(f"AAS read failed: {aas_r.status}")
    submodels=[]
    for sm in fixture.get("submodels",[]):
        r=adapter.read_submodel(sm["id"])
        if r.status != 200 or not isinstance(r.payload,dict): raise RuntimeError(f"Submodel read failed {sm['id']}: {r.status}")
        submodels.append(r.payload)
    cds=[]
    for cd in fixture.get("conceptDescriptions",[]):
        r=adapter.read_concept_description(cd["id"])
        if r.status != 200 or not isinstance(r.payload,dict): raise RuntimeError(f"ConceptDescription read failed {cd['id']}: {r.status}")
        cds.append(r.payload)
    returned={"assetAdministrationShells":[aas_r.payload],"submodels":submodels,"conceptDescriptions":cds}; (out_dir/"returned-environment.json").write_text(json.dumps(returned,ensure_ascii=False,indent=2),encoding="utf-8")
    results=[AssessmentResult("AAS-T001","PASS","SUPPORTED_VERIFIED","repository-local P-AAS executable subset loaded",[],[])]
    sample=normalize_bundle(returned,{"capabilities":[c.capability_id for c in capabilities if c.status in {CapabilityStatus.SUPPORTED_VERIFIED,CapabilityStatus.SUPPORTED_NOT_VERIFIED}]})
    for check in run_core_semantic_checks(sample): results.append(AssessmentResult(CHECK_TO_TEST[check.check_id],"PASS" if check.passed else "FAIL","SUPPORTED_VERIFIED",check.message,_assertion(check),[]))
    core_pass=all(cmap.get(cap) and cmap[cap].status in {CapabilityStatus.SUPPORTED_VERIFIED,CapabilityStatus.SUPPORTED_NOT_VERIFIED} for cap in ["read_aas","read_submodel","read_concept_description"])
    results.append(AssessmentResult("AAS-T009","PASS" if core_pass else "FAIL","SUPPORTED_VERIFIED" if core_pass else "UNSUPPORTED_WITH_EVIDENCE","core repository capabilities verified" if core_pass else "missing core capability",[],[]))
    for cap,tid in CORE_CAPS.items(): results.append(external_result(tid,cmap[cap],required=True,passed=True,reason=f"{cap} returned 200"))
    for cap,tids in OPTIONAL.items():
        c=cmap[cap]
        for tid in tids: results.append(classify_optional(tid,c))

    aasx_cap=cmap["aasx_package"]
    if aasx_cap.status == CapabilityStatus.UNSUPPORTED_WITH_EVIDENCE:
        results.append(classify_optional("AAS-T018",aasx_cap)); results.append(classify_optional("AAS-T019",aasx_cap))
    else:
        try:
            serialized=adapter.serialize_aasx([aas_id],[sm["id"] for sm in fixture.get("submodels",[])],include_concept_descriptions=True)
            aasx_path=out_dir/"serialized.aasx"
            if serialized.status == 200:
                aasx_path.write_bytes(serialized.raw_body)
            checks=validate_aasx(aasx_path,set()) if serialized.status == 200 and serialized.raw_body.startswith(b"PK") else []
            core_checks=[c for c in checks if c.check_id != "aasx-supplementary"]
            package_ok=serialized.status == 200 and serialized.raw_body.startswith(b"PK") and bool(core_checks) and all(c.passed for c in core_checks)
            artifact=_artifact(aasx_path,"ART-P-AAS-V2-AASX","application/asset-administration-shell-package+xml") if aasx_path.exists() else None
            assertions=[{"assertion_id":c.check_id,"status":"PASS" if c.passed else "FAIL","expected":"valid AASX core package","observed":c.observed,"message":c.message} for c in core_checks]
            if package_ok:
                capabilities=_promote(capabilities,"aasx_package","/serialization returned valid AASX package",serialized.status,"/serialization",[aasx_path.name]); cmap=_cap_map(capabilities)
                implementation=str(adapter.target_metadata.get("implementation","external AAS"))
                results.append(AssessmentResult("AAS-T018","PASS","SUPPORTED_VERIFIED",f"{implementation} /serialization returned a valid AASX core package",assertions,[artifact] if artifact else []))
                required_supp=_supplementary_refs(fixture)
                if not required_supp:
                    results.append(AssessmentResult("AAS-T019","NOT_APPLICABLE","SUPPORTED_VERIFIED","fixture_has_no_supplementary_files; AASX package serialization verified but supplementary linkage not exercised",[{"assertion_id":"supplementary-fixture","status":"NOT_APPLICABLE","expected":"supplementary files only when fixture contains File references","observed":[],"message":"fixture_has_no_supplementary_files"}],[artifact] if artifact else []))
                else:
                    supp=next((c for c in checks if c.check_id=="aasx-supplementary"),None)
                    results.append(AssessmentResult("AAS-T019","PASS" if supp and supp.passed else "FAIL","SUPPORTED_VERIFIED",supp.message if supp else "supplementary validation missing",_assertion(supp) if supp else [],[artifact] if artifact else []))
            else:
                results.append(AssessmentResult("AAS-T018","FAIL",aasx_cap.status.value,f"/serialization did not yield a valid AASX package (HTTP {serialized.status})",assertions,[artifact] if artifact else []))
                results.append(AssessmentResult("AAS-T019","BLOCKED",aasx_cap.status.value,"AASX core validation failed before supplementary validation",[],[artifact] if artifact else []))
        except TransportBlocked as exc:
            results.append(AssessmentResult("AAS-T018","BLOCKED","BLOCKED",str(exc),[],[])); results.append(AssessmentResult("AAS-T019","BLOCKED","BLOCKED","serialization transport blocked",[],[]))

    by_id={r.test_id:r for r in results}; ordered=[by_id[f"AAS-T{i:03d}"] for i in range(1,20)]
    write_outputs(out_dir,adapter.target_metadata,capabilities,ordered)
    required={f"AAS-T{i:03d}" for i in list(range(1,10))+[11,12,18]}; required_failures=sum(1 for r in ordered if r.test_id in required and r.result in {"FAIL","BLOCKED"})
    return {"required_failures":required_failures,"results":[r.to_dict() for r in ordered],"capabilities":[c.to_dict() for c in capabilities]}
