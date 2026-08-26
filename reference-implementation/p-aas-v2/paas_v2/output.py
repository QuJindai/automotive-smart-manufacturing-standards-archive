from __future__ import annotations

import csv, hashlib, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .assessment import AssessmentResult
from .external import CapabilityRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_outputs(out_dir: Path, target: dict[str, Any], capabilities: list[CapabilityRecord], results: list[AssessmentResult]) -> dict[str, str]:
    out_dir.mkdir(parents=True,exist_ok=True)
    matrix=[c.to_dict() for c in capabilities]
    matrix_json=out_dir/"implementation-capability-matrix.json"; matrix_json.write_text(json.dumps(matrix,ensure_ascii=False,indent=2),encoding="utf-8")
    matrix_csv=out_dir/"implementation-capability-matrix.csv"
    fields=["capability_id","profile_test_ids","advertised","verified","status","source","observed_endpoint","http_status","reason","artifact_refs"]
    with matrix_csv.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for row in matrix:
            row=dict(row); row["profile_test_ids"]=";".join(row["profile_test_ids"]); row["artifact_refs"]=";".join(row["artifact_refs"]); w.writerow(row)
    counts=Counter(r.result for r in results)
    summary={"schema_version":"1.0","target":target,"certification_claim":False,"counts":{k:counts.get(k,0) for k in ["PASS","FAIL","BLOCKED","NOT_APPLICABLE"]},"capability_counts":dict(Counter(c.status.value for c in capabilities)),"generated_at":_now()}
    summary_path=out_dir/"interop-summary.json"; summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    test_results=[]
    for r in results:
        assertions=r.assertions or [{"assertion_id":"external-assessment","status":r.result,"expected":"Profile-specific expected behavior","observed":r.reason,"message":r.capability_status}]
        test_results.append({"test_id":r.test_id,"level":"C1","result":r.result,"executed_at":_now(),"executor":"p-aas-v2","linked_rule_ids":[],"metrics":{},"observations":r.reason,"assertions":assertions,"artifacts":r.artifacts,"deviations":[]})
    evidence={"schema_version":"1.0","evidence_bundle_id":"EVB-P-AAS-V2-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),"profile_version":"P-AAS-V2","system_under_test":{"name":target.get("implementation","external AAS"),"version":str(target.get("version","unknown")),"site":"public-ci-or-external","asset_ids":[],"model_ids":[]},"run_started_at":_now(),"run_completed_at":_now(),"environment":{"adapter":"external","certification_claim":False},"test_results":test_results,"bundle_sha256":None,"signatures":[]}
    evidence_path=out_dir/"evidence-bundle.json"; evidence_path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"matrix_json":str(matrix_json),"matrix_csv":str(matrix_csv),"summary":str(summary_path),"evidence":str(evidence_path)}
