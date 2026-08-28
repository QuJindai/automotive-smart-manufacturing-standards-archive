#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";

const packageDir = process.argv[2];
if (!packageDir) { console.error("usage: node verify.mjs <package-dir>"); process.exit(2); }
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../../..");
const cac = JSON.parse(fs.readFileSync(path.join(repoRoot, "machine-readable/p0-08/conformance-criteria-v1.json"), "utf8"));
const criteria = cac.criteria ?? [];
const criteriaByTest = new Map(criteria.map(row => [row.test_id, row]));
const expectedAutomatable = criteria.filter(row => row.required === true && row.automation_flag === true).length;

const LEVEL_ORDER = {C0:0,C1:1,C2:2,C3:3};
const ROLE_BY_LEVEL = {C0:"SUPPLIER_DECLARANT",C1:"LAB_EVALUATOR",C2:"FAT_SAT_EVALUATOR",C3:"OPERATIONS_MONITOR"};
const REQUIRED_PROOFS = {
  C0:new Set(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST"]),
  C1:new Set(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST","LAB_REPORT","ATTESTATION"]),
  C2:new Set(["AUTOMATED_TEST","LAB_REPORT","FAT_SAT_EVIDENCE","ATTESTATION"]),
  C3:new Set(["AUTOMATED_TEST","FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE","ATTESTATION"]),
};
const MATERIAL_KEYS=["profile_version","program_version","parameter_hash","interface_version"];
const METRICS=["machine_readable_coverage","requirement_testability","automation_rate","evidence_completeness","applicable_required_pass_rate","cross_implementation_reproducibility","regression_stability","c3_drift_closure_rate"];
const UPSTREAM={
  "P0-02":{stage:"R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION",field:"p0_02_status_blob_sha"},
  "P0-06":{stage:"R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE",field:"p0_06_status_blob_sha"},
};

const sha256=data=>crypto.createHash("sha256").update(data).digest("hex");
const safeUri=uri=>typeof uri==="string"&&uri.length>0&&!uri.includes("://")&&!path.isAbsolute(uri)&&!uri.split(/[\\/]+/).includes("..");
const parseUtc=v=>typeof v==="string"&&v.endsWith("Z")?Date.parse(v):NaN;
const deepEqual=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

let pkg;
try { pkg=JSON.parse(fs.readFileSync(path.join(packageDir,"package.json"),"utf8")); }
catch(err){ console.log(JSON.stringify({valid:false,error:String(err)})); process.exit(1); }

const refs=pkg.evidence_refs??[];
const refsById=new Map(refs.map(r=>[r.evidence_id,r]));
function refValid(ref){
  if(!ref||!safeUri(ref.uri)) return false;
  try{const data=fs.readFileSync(path.join(packageDir,ref.uri)); return data.length===Number(ref.size_bytes)&&sha256(data)===ref.sha256;}catch{return false;}
}
function proofJson(ref){
  if(!refValid(ref)) return null;
  try{const x=JSON.parse(fs.readFileSync(path.join(packageDir,ref.uri),"utf8")); return x&&typeof x==="object"?x:null;}catch{return null;}
}
const evidenceHashesValid=refs.length>0&&refs.every(refValid)&&refsById.size===refs.length;
const evidenceIds=new Set(refs.map(r=>r.evidence_id));

function upstreamProof(standardId){
  const cfg=UPSTREAM[standardId], baseline=pkg.baseline??{};
  for(const ref of refs){
    if(ref.source_stage!==cfg.stage) continue;
    const p=proofJson(ref);
    if(p&&p.standard_id===standardId&&p.source_stage===cfg.stage&&p.status==="PASS"&&p.required_failures===0&&p.source_blob_sha===baseline[cfg.field]&&p.certification_claim===false) return p;
  }
  return null;
}
function chainValid(level){
  const row=(pkg.assurance_chain??[]).find(x=>x.level===level);
  if(!row) return false;
  const ref=refsById.get(row.evidence_id), proof=proofJson(ref), now=parseUtc(pkg.assessment_time), until=parseUtc(row.valid_until);
  return Boolean(ref&&ref.proof_type==="ATTESTATION"&&proof&&Number.isFinite(now)&&Number.isFinite(until)&&now<=until&&row.decision==="PASS"&&row.lifecycle_state==="VALID"&&row.assessment_id&&proof.statement_type==="CONFORMITY_EVALUATION_STATEMENT"&&proof.assessment_id===row.assessment_id&&proof.assessment_level===row.level&&proof.decision===row.decision&&proof.lifecycle_state===row.lifecycle_state&&proof.valid_until===row.valid_until&&proof.certification_claim===false);
}

const level=pkg.assessment_level, levelIndex=LEVEL_ORDER[level]??-1;
const types=new Set(refs.map(r=>String(r.proof_type)));
const proofSetValid=[...(REQUIRED_PROOFS[level]??new Set())].every(x=>types.has(x));
const roleValid=ROLE_BY_LEVEL[level]===pkg.assessor?.role&&typeof pkg.assessor?.assessor_id==="string"&&pkg.assessor.assessor_id.length>0;
const execution=pkg.execution_summary??{};
const automationValid=execution.manual_passed_automatable===0&&execution.automatable_required===expectedAutomatable&&execution.automated_executed===expectedAutomatable&&refs.filter(r=>r.proof_type==="AUTOMATED_TEST").every(r=>r.execution_mode==="AUTOMATED");
const naValid=(pkg.not_applicable??[]).every(row=>criteriaByTest.get(row.test_id)?.na_allowed===true&&typeof row.justification==="string"&&row.justification.length>0);
const exceptionValid=(pkg.exceptions??[]).every(row=>row.masks_required_failure!==true);

const p002=upstreamProof("P0-02"), p006=upstreamProof("P0-06");
let predecessorRulesValid=true;
if(level==="C0") predecessorRulesValid=["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST"].every(x=>types.has(x));
else if(level==="C1") predecessorRulesValid=chainValid("C0")&&types.has("LAB_REPORT")&&Boolean(p002);
else if(level==="C2") predecessorRulesValid=chainValid("C0")&&chainValid("C1")&&Boolean(pkg.project_binding?.project_id)&&Boolean(pkg.project_binding?.instance_id)&&Boolean(p006);
else if(level==="C3"){
  const start=parseUtc(pkg.continuous_monitoring?.window_start),end=parseUtc(pkg.continuous_monitoring?.window_end),days=Number.isFinite(start)&&Number.isFinite(end)?(end-start)/86400000:-1;
  predecessorRulesValid=chainValid("C0")&&chainValid("C1")&&chainValid("C2")&&Boolean(pkg.project_binding?.project_id)&&Boolean(pkg.project_binding?.instance_id)&&Boolean(p006)&&pkg.continuous_monitoring?.coverage_ratio===1.0&&days>=Number(pkg.continuous_monitoring?.required_days??0)&&types.has("CONTINUOUS_EVIDENCE");
}else predecessorRulesValid=false;

const baseline=pkg.baseline??{}, observed=pkg.observed_baseline??{};
let baselineBindingsValid=MATERIAL_KEYS.every(k=>baseline[k]!==undefined&&baseline[k]!==""&&observed[k]!==undefined&&observed[k]!=="");
if(levelIndex>=1) baselineBindingsValid=baselineBindingsValid&&Boolean(p002);
if(levelIndex>=2) baselineBindingsValid=baselineBindingsValid&&Boolean(p006);
const materialDrift=MATERIAL_KEYS.some(k=>baseline[k]!==observed[k])||(pkg.drifts??[]).some(r=>r.material===true&&r.status!=="CLOSED");
const driftDeclarationValid=pkg.declared_material_drift===materialDrift;

const now=parseUtc(pkg.assessment_time),from=parseUtc(pkg.validity?.valid_from),until=parseUtc(pkg.validity?.valid_until);
const expired=!Number.isFinite(now)||!Number.isFinite(until)||now>until, notYet=!Number.isFinite(now)||!Number.isFinite(from)||now<from;
const revoked=pkg.validity?.revoked===true, superseded=pkg.validity?.superseded===true;
let lifecycleState=revoked?"REVOKED":superseded?"SUPERSEDED":expired?"EXPIRED":materialDrift?"REEVALUATION_REQUIRED":"VALID";
const reevaluationExpected=(materialDrift||expired||revoked||superseded)?"REQUIRED":"NOT_REQUIRED";
const reevaluationValid=pkg.claimed_reevaluation_state===reevaluationExpected;
const validityFieldsValid=!notYet;

const outcomes=pkg.required_outcomes??[], outcomeStates=outcomes.map(r=>r.result);
const overallDecision=outcomeStates.includes("FAIL")?"FAIL":outcomeStates.includes("BLOCKED")?"BLOCKED":"PASS";
const overallDecisionValid=outcomes.length>0&&pkg.declared_decision===overallDecision&&!("weighted_score" in pkg);

function metricVector(){
  const out={},passCount=outcomes.filter(r=>r.result==="PASS").length;
  for(const name of METRICS){
    const row=pkg.effectiveness_sources?.[name]??{}, n=row.numerator,d=row.denominator,src=row.source_evidence_ids;
    let ok=Number.isInteger(n)&&Number.isInteger(d)&&n>=0&&d>=0&&n<=d&&Array.isArray(src)&&src.length>0&&src.every(id=>evidenceIds.has(id));
    if(name==="requirement_testability") ok=ok&&n===20&&d===20;
    else if(name==="automation_rate") ok=ok&&n===expectedAutomatable&&d===expectedAutomatable;
    else if(name==="evidence_completeness") ok=ok&&n===refs.filter(refValid).length&&d===evidenceIds.size;
    else if(name==="applicable_required_pass_rate") ok=ok&&n===passCount&&d===outcomes.length;
    out[name]={numerator:n,denominator:d,source_evidence_ids:src,status:ok?(d===0?"NOT_APPLICABLE":"MEASURED"):"INVALID",value:ok&&d!==0?n/d:null};
  }
  return out;
}
const metrics=metricVector();
const metricsValid=deepEqual(metrics,pkg.claimed_effectiveness_metrics??{})&&Object.values(metrics).every(r=>r.status!=="INVALID");

const bindings=new Map((pkg.trace_bindings??[]).map(r=>[r.test_id,r]));
let traceValid=bindings.size===20;
for(let i=1;i<=20&&traceValid;i++){
  const tid=`CAE-T${String(i).padStart(3,"0")}`,rid=`CAE-R${String(i).padStart(3,"0")}`,b=bindings.get(tid);
  if(!b||b.requirement_id!==rid||!Array.isArray(b.evidence_ids)||b.evidence_ids.length===0||b.evidence_ids.some(id=>!evidenceIds.has(id))) traceValid=false;
}
const statementValid=pkg.certification_claim===false&&pkg.statement_type==="CONFORMITY_EVALUATION_STATEMENT"&&["UNSIGNED","SIGNED_VERIFIED","SIGNED_UNVERIFIED"].includes(pkg.signature_state)&&(pkg.signature_state!=="UNSIGNED"||!pkg.signature);

const valid=evidenceHashesValid&&proofSetValid&&roleValid&&automationValid&&naValid&&exceptionValid&&predecessorRulesValid&&baselineBindingsValid&&driftDeclarationValid&&reevaluationValid&&validityFieldsValid&&overallDecisionValid&&metricsValid&&traceValid&&statementValid;
console.log(JSON.stringify({valid,overall_decision:overallDecision,lifecycle_state:lifecycleState,evidence_hashes_valid:evidenceHashesValid,metrics_valid:metricsValid,predecessor_rules_valid:predecessorRulesValid,baseline_bindings_valid:baselineBindingsValid,drift_declaration_valid:driftDeclarationValid,reevaluation_valid:reevaluationValid,role_valid:roleValid,proof_set_valid:proofSetValid,automation_valid:automationValid,trace_valid:traceValid,certification_claim:pkg.certification_claim===true}));
process.exit(valid?0:1);
