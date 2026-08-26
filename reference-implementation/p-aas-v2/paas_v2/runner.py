from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from .assessment import AssessmentResult, classify_optional, external_result
from .external import CapabilityRecord, CapabilityStatus, ExternalAASAdapter
from .output import write_outputs
from .v1_bridge import normalize_bundle, run_core_semantic_checks

CHECK_TO_TEST={"asset-kind":"AAS-T002","asset-identifier":"AAS-T003","required-semantics":"AAS-T004","iec61360":"AAS-T005","preferred-languages":"AAS-T006","unit-consistency":"AAS-T007","unit-resolvability":"AAS-T008"}
CORE_CAPS={"read_aas":"AAS-T011","read_submodel":"AAS-T012"}
OPTIONAL={"query":["AAS-T010"],"authorization":["AAS-T013","AAS-T014","AAS-T015","AAS-T016"],"signed":["AAS-T017"],"aasx_package":["AAS-T018","AAS-T019"]}


def _cap_map(capabilities: list[CapabilityRecord]) -> dict[str, CapabilityRecord]:
    return {c.capability_id:c for c in capabilities}


def _assertion(check) -> list[dict[str, Any]]:
    return [{"assertion_id":check.check_id,"status":"PASS" if check.passed else "FAIL","expected":"P-AAS V1 rule satisfied","observed":check.observed,"message":check.message}]


def run_external(adapter: ExternalAASAdapter, fixture: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    health=adapter.health()
    if health.status != 200: raise RuntimeError(f"external OpenAPI health failed: {health.status}")
    (out_dir/"openapi.json").write_text(json.dumps(health.payload,ensure_ascii=False,indent=2),encoding="utf-8")
    capabilities=adapter.discover_capabilities(); cmap=_cap_map(capabilities)
    imp=adapter.import_environment(fixture)
    (out_dir/"import-response.json").write_text(json.dumps({"success":imp.success,"route":imp.route,"responses":imp.responses,"reason":imp.reason},ensure_ascii=False,indent=2),encoding="utf-8")
    if not imp.success: raise RuntimeError("fixture import failed: "+imp.reason)
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
    by_id={r.test_id:r for r in results}; ordered=[by_id[f"AAS-T{i:03d}"] for i in range(1,20)]
    write_outputs(out_dir,adapter.target_metadata,capabilities,ordered)
    required={f"AAS-T{i:03d}" for i in list(range(1,10))+[11,12]}; required_failures=sum(1 for r in ordered if r.test_id in required and r.result in {"FAIL","BLOCKED"})
    return {"required_failures":required_failures,"results":[r.to_dict() for r in ordered],"capabilities":[c.to_dict() for c in capabilities]}
