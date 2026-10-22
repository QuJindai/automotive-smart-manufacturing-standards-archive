#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";

const packageDir = process.argv[2];
if (!packageDir) { console.error("usage: node verify.mjs <package-dir>"); process.exit(2); }
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../../..");
const cacPath = path.join(repoRoot, "machine-readable/p0-08/conformance-criteria-v1.json");
const cacBytes = fs.readFileSync(cacPath);
const cac = JSON.parse(cacBytes.toString("utf8"));
const profile = JSON.parse(fs.readFileSync(path.join(repoRoot, "machine-readable/p0-08/automotive-profile-v1.json"), "utf8"));
const packageSchema = JSON.parse(fs.readFileSync(path.join(repoRoot, "machine-readable/p0-08/conformity-assessment-v1.schema.json"), "utf8"));
const criteria = cac.criteria ?? [];
const criteriaByTest = new Map(criteria.map(row => [row.test_id, row]));
const expectedAutomatable = criteria.filter(row => row.required === true && row.automation_flag === true).length;

const LEVEL_ORDER = {C0:0,C1:1,C2:2,C3:3};
const ROLE_BY_LEVEL = {C0:"SUPPLIER_DECLARANT",C1:"LAB_EVALUATOR",C2:"FAT_SAT_EVALUATOR",C3:"OPERATIONS_MONITOR"};
const REQUIRED_PROOFS = {
  C0:new Set(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST"]),
  C1:new Set(["AUTOMATED_TEST","LAB_REPORT","ATTESTATION"]),
  C2:new Set(["FAT_SAT_EVIDENCE","ATTESTATION"]),
  C3:new Set(["FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE","ATTESTATION"]),
};
const PROOF_TYPES=new Set(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST","LAB_REPORT","FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE","ATTESTATION","EXCEPTION_RECORD"]);
const DIRECT_PROOF_TYPES=new Set(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST","LAB_REPORT","FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE"]);
const MATERIAL_KEYS=["profile_version","program_version","parameter_hash","interface_version","p0_02_status_blob_sha","p0_06_status_blob_sha"];
const METRICS=["machine_readable_coverage","requirement_testability","automation_rate","evidence_completeness","applicable_required_pass_rate","cross_implementation_reproducibility","regression_stability","c3_drift_closure_rate"];
const UPSTREAM={
  "P0-02":{stage:"R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION",field:"p0_02_status_blob_sha"},
  "P0-06":{stage:"R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE",field:"p0_06_status_blob_sha"},
};

const sha256=data=>crypto.createHash("sha256").update(data).digest("hex");
const gitBlobSha=data=>crypto.createHash("sha1").update(`blob ${data.length}\0`).update(data).digest("hex");
const safeUri=uri=>typeof uri==="string"&&uri.length>0&&!uri.includes("://")&&!path.isAbsolute(uri)&&!uri.split(/[\\/]+/).includes("..");
const parseUtc=v=>typeof v==="string"&&v.endsWith("Z")?Date.parse(v):NaN;
const deepEqual=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==="object"?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const canonicalSha256=value=>sha256(Buffer.from(JSON.stringify(canonical(value)),"utf8"));
function schemaValid(value,schema,root=packageSchema){
  if(schema.$ref){
    if(typeof schema.$ref!=="string"||!schema.$ref.startsWith("#/")) return false;
    let target=root;
    try{for(const token of schema.$ref.slice(2).split("/")) target=target[token.replaceAll("~1","/").replaceAll("~0","~")];}
    catch{return false;}
    return Boolean(target&&typeof target==="object"&&schemaValid(value,target,root));
  }
  const types=Array.isArray(schema.type)?schema.type:schema.type?[schema.type]:[];
  const typeValid=name=>name==="object"?value!==null&&typeof value==="object"&&!Array.isArray(value):name==="array"?Array.isArray(value):name==="string"?typeof value==="string":name==="integer"?Number.isInteger(value):name==="number"?typeof value==="number"&&Number.isFinite(value):name==="boolean"?typeof value==="boolean":name==="null"?value===null:false;
  if(types.length>0&&!types.some(typeValid)) return false;
  if(Object.hasOwn(schema,"const")&&!deepEqual(value,schema.const)) return false;
  if(Array.isArray(schema.enum)&&!schema.enum.some(item=>deepEqual(value,item))) return false;
  if(value!==null&&typeof value==="object"&&!Array.isArray(value)){
    const properties=schema.properties??{};
    if((schema.required??[]).some(name=>!Object.hasOwn(value,name))) return false;
    if(schema.additionalProperties===false&&Object.keys(value).some(name=>!Object.hasOwn(properties,name))) return false;
    if(Object.entries(value).some(([name,item])=>Object.hasOwn(properties,name)&&!schemaValid(item,properties[name],root))) return false;
  }else if(Array.isArray(value)){
    if(value.length<(schema.minItems??0)||(Number.isInteger(schema.maxItems)&&value.length>schema.maxItems)) return false;
    if(schema.items&&value.some(item=>!schemaValid(item,schema.items,root))) return false;
  }else if(typeof value==="string"){
    if(value.length<(schema.minLength??0)) return false;
    if(schema.pattern&&!(new RegExp(schema.pattern)).test(value)) return false;
    if(schema.format==="date-time"&&(!value.endsWith("Z")||!Number.isFinite(Date.parse(value)))) return false;
  }else if(typeof value==="number"){
    if(Object.hasOwn(schema,"minimum")&&value<schema.minimum) return false;
    if(Object.hasOwn(schema,"maximum")&&value>schema.maximum) return false;
  }
  return true;
}

let pkg;
try { pkg=JSON.parse(fs.readFileSync(path.join(packageDir,"package.json"),"utf8")); }
catch(err){ console.log(JSON.stringify({valid:false,error:String(err)})); process.exit(1); }
const packageSchemaValid=schemaValid(pkg,packageSchema);
const isObject=value=>value!==null&&typeof value==="object"&&!Array.isArray(value);
const objectFields=["profile","criteria_registry","assessor","assessment_object","baseline","observed_baseline","execution_summary","effectiveness_sources","claimed_effectiveness_metrics","validity","statement_scope"];
const listFields=["evidence_refs","not_applicable","exceptions","assurance_chain","required_outcomes","drifts","trace_bindings"];
const runtimeShapeSafe=isObject(pkg)&&objectFields.every(name=>isObject(pkg[name]))&&listFields.every(name=>Array.isArray(pkg[name])&&pkg[name].every(isObject))&&["project_binding","continuous_monitoring","signature"].every(name=>!Object.hasOwn(pkg,name)||isObject(pkg[name]))&&["effectiveness_sources","claimed_effectiveness_metrics"].every(section=>METRICS.every(name=>isObject(pkg[section][name])));
const registryValid=runtimeShapeSafe&&pkg.criteria_registry.registry_id===cac.registry_id&&pkg.criteria_registry.registry_version===cac.registry_version&&pkg.criteria_registry.sha256===sha256(cacBytes);
if(!runtimeShapeSafe){
  console.log(JSON.stringify({valid:false,overall_decision:"FAIL",lifecycle_state:"REEVALUATION_REQUIRED",schema_valid:false,registry_valid:false,evidence_hashes_valid:false,metrics_valid:false,predecessor_rules_valid:false,baseline_bindings_valid:false,drift_declaration_valid:false,reevaluation_valid:false,role_valid:false,proof_set_valid:false,proof_semantics_valid:false,automation_valid:false,outcomes_valid:false,trace_valid:false,statement_valid:false,certification_claim:false}));
  process.exit(1);
}

const refs=pkg.evidence_refs??[];
const refsById=new Map(refs.map(r=>[r.evidence_id,r]));
function refValid(ref){
  if(!ref||!safeUri(ref.uri)||ref.media_type!=="application/json") return false;
  try{
    const root=fs.realpathSync(packageDir);
    let target=root;
    for(const part of ref.uri.split(/[\\/]+/)){
      target=path.join(target,part);
      if(fs.lstatSync(target).isSymbolicLink()) return false;
    }
    target=fs.realpathSync(target);
    const relative=path.relative(root,target);
    if(relative.startsWith("..")||path.isAbsolute(relative)) return false;
    const data=fs.readFileSync(target);
    return data.length===Number(ref.size_bytes)&&sha256(data)===ref.sha256;
  }catch{return false;}
}
function proofJson(ref){
  if(!refValid(ref)) return null;
  try{const x=JSON.parse(fs.readFileSync(path.join(packageDir,ref.uri),"utf8")); return x&&typeof x==="object"?x:null;}catch{return null;}
}

function directRefProof(ref){
  const proofType=ref?.proof_type;
  if(!ref||ref.source_stage||!DIRECT_PROOF_TYPES.has(proofType)) return null;
  const project=pkg.project_binding??{}, monitoring=pkg.continuous_monitoring??{};
  const proof=proofJson(ref);
  if(!proof||proof.kind!==proofType||proof.assessment_object_id!==pkg.assessment_object?.object_id||proof.assessment_object_type!==pkg.assessment_object?.object_type||proof.baseline_sha256!==canonicalSha256(pkg.baseline??{})) return null;
  if(proofType==="MODEL"&&proof.machine_readable===true&&typeof proof.model_id==="string"&&proof.model_id.length>0) return proof;
  if(proofType==="PROFILE_DECLARATION"&&proof.profile_id===pkg.profile?.id&&proof.profile_version===pkg.profile?.version) return proof;
  if(proofType==="AUTOMATED_TEST"&&proof.result==="PASS"&&proof.execution_mode==="AUTOMATED"&&ref.execution_mode==="AUTOMATED") return proof;
  if(proofType==="LAB_REPORT"&&proof.result==="PASS"&&proof.tck==="P-CAE-TCK-1.0"&&typeof proof.lab_id==="string"&&proof.lab_id.length>0) return proof;
  if(proofType==="FAT_SAT_EVIDENCE"&&proof.fat==="PASS"&&proof.sat==="PASS"&&proof.project_id===project.project_id&&proof.instance_id===project.instance_id) return proof;
  if(proofType==="CONTINUOUS_EVIDENCE"&&proof.coverage_ratio===monitoring.coverage_ratio&&proof.coverage_ratio===1.0&&proof.window_start===monitoring.window_start&&proof.window_end===monitoring.window_end&&Number.isInteger(proof.material_open_drifts)&&proof.material_open_drifts>=0) return proof;
  return null;
}
function directProof(proofType){
  for(const ref of refs){
    if(ref.proof_type!==proofType) continue;
    const proof=directRefProof(ref);
    if(proof) return {ref,proof};
  }
  return null;
}
const directProofValid=proofType=>Boolean(directProof(proofType));
const allDirectProofsValid=refs.filter(ref=>!ref.source_stage&&DIRECT_PROOF_TYPES.has(ref.proof_type)).every(ref=>Boolean(directRefProof(ref)));
const evidenceHashesValid=refs.length>0&&refs.every(refValid)&&refsById.size===refs.length;
const evidenceIds=new Set(refs.map(r=>r.evidence_id));
const validEvidenceIds=new Set(refs.filter(refValid).map(r=>r.evidence_id));

function upstreamStatus(standardId){
  const anchor=(profile.upstream_sources??[]).find(row=>row.standard_id===standardId);
  if(!anchor) return null;
  try{
    const source=path.resolve(repoRoot,anchor.status_path);
    const relative=path.relative(repoRoot,source);
    if(relative.startsWith("..")||path.isAbsolute(relative)||fs.lstatSync(source).isSymbolicLink()) return null;
    const data=fs.readFileSync(source);
    if(gitBlobSha(data)!==anchor.status_blob_sha) return null;
    const status=JSON.parse(data.toString("utf8"));
    return status&&typeof status==="object"&&!Array.isArray(status)?status:null;
  }catch{return null;}
}
function upstreamProof(standardId){
  const cfg=UPSTREAM[standardId], baseline=pkg.baseline??{};
  const anchor=(profile.upstream_sources??[]).find(row=>row.standard_id===standardId),status=upstreamStatus(standardId);
  if(!anchor||!status||baseline[cfg.field]!==anchor.status_blob_sha) return null;
  for(const ref of refs){
    if(ref.source_stage!==cfg.stage) continue;
    const p=proofJson(ref);
    let summaryValid=true;
    if(standardId==="P0-02"){
      const targets=Array.isArray(status.targets)?status.targets:[];
      summaryValid=p?.total_implementations===targets.length&&p?.verified_implementations===targets.filter(target=>target&&typeof target==="object"&&target.required_failures===0).length;
    }else if(standardId==="P0-06"){
      summaryValid=p?.golden_packages===Object.keys(status.golden_packages??{}).length&&p?.negative_false_pass_count===status.negative_test_kit?.false_pass_count&&p?.independent_verifier===status.cross_implementation?.independent_node_verifier;
    }
    if(p&&p.standard_id===standardId&&p.source_stage===cfg.stage&&p.status==="PASS"&&p.required_failures===0&&p.source_path===anchor.status_path&&p.source_blob_sha===anchor.status_blob_sha&&p.certification_claim===false&&summaryValid) return p;
  }
  return null;
}
function chainValid(level){
  const row=(pkg.assurance_chain??[]).find(x=>x.level===level);
  if(!row) return false;
  const ref=refsById.get(row.evidence_id), proof=proofJson(ref), now=parseUtc(pkg.assessment_time), until=parseUtc(row.valid_until);
  return Boolean(ref&&ref.proof_type==="ATTESTATION"&&proof&&Number.isFinite(now)&&Number.isFinite(until)&&now<=until&&row.decision==="PASS"&&row.lifecycle_state==="VALID"&&row.assessment_id&&proof.statement_type==="CONFORMITY_EVALUATION_STATEMENT"&&proof.assessment_id===row.assessment_id&&proof.assessment_level===row.level&&proof.decision===row.decision&&proof.lifecycle_state===row.lifecycle_state&&proof.valid_until===row.valid_until&&proof.assessment_object_id===pkg.assessment_object?.object_id&&proof.assessment_object_type===pkg.assessment_object?.object_type&&proof.profile_id===pkg.profile?.id&&proof.profile_version===pkg.profile?.version&&proof.baseline_sha256===canonicalSha256(pkg.baseline??{})&&proof.certification_claim===false);
}

const level=pkg.assessment_level, levelIndex=LEVEL_ORDER[level]??-1;
const identityValid=packageSchemaValid&&pkg.schema_version==="1.0"&&typeof pkg.assessment_id==="string"&&pkg.assessment_id.length>0&&pkg.profile?.id==="P-CAE-AUTO-R14"&&pkg.profile?.version==="1.0"&&level in LEVEL_ORDER;
const types=new Set(refs.map(r=>String(r.proof_type)));
const proofSetValid=[...(REQUIRED_PROOFS[level]??new Set())].every(x=>types.has(x));
const roleValid=ROLE_BY_LEVEL[level]===pkg.assessor?.role&&typeof pkg.assessor?.assessor_id==="string"&&pkg.assessor.assessor_id.length>0;
const execution=pkg.execution_summary??{};
const automationValid=execution.manual_passed_automatable===0&&execution.automatable_required===expectedAutomatable&&execution.automated_executed===expectedAutomatable&&refs.filter(r=>r.proof_type==="AUTOMATED_TEST").every(r=>r.execution_mode==="AUTOMATED");
const outcomes=pkg.required_outcomes??[];
const expectedOutcomeIds=new Set(criteria.filter(row=>row.required===true).map(row=>row.requirement_id));
const outcomeIds=outcomes.map(row=>String(row.requirement_id));
const outcomeMap=new Map(outcomes.map(row=>[String(row.requirement_id),row.result]));
const outcomesValid=outcomeIds.length===expectedOutcomeIds.size&&new Set(outcomeIds).size===outcomeIds.length&&outcomeIds.every(id=>expectedOutcomeIds.has(id))&&outcomes.every(row=>["PASS","FAIL","BLOCKED","NOT_APPLICABLE"].includes(row.result));
const naRecords=pkg.not_applicable??[], naByTest=new Map(naRecords.map(row=>[String(row.test_id),row]));
let naValid=outcomesValid&&naByTest.size===naRecords.length;
for(const criterion of criteria){
  const result=outcomeMap.get(String(criterion.requirement_id)), record=naByTest.get(String(criterion.test_id));
  if(result==="NOT_APPLICABLE"&&!(criterion.na_allowed===true&&record&&typeof record.justification==="string"&&record.justification.length>0)) naValid=false;
  if(record&&!(criterion.na_allowed===true&&result==="NOT_APPLICABLE"&&typeof record.justification==="string"&&record.justification.length>0)) naValid=false;
}
const exceptionValid=(pkg.exceptions??[]).every(row=>row.masks_required_failure!==true);

let levelProofSemanticsValid=true;
if(level==="C0") levelProofSemanticsValid=["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST"].every(directProofValid);
else if(level==="C1") levelProofSemanticsValid=directProofValid("LAB_REPORT");
else if(level==="C2") levelProofSemanticsValid=directProofValid("FAT_SAT_EVIDENCE");
else if(level==="C3") levelProofSemanticsValid=directProofValid("FAT_SAT_EVIDENCE")&&directProofValid("CONTINUOUS_EVIDENCE");
else levelProofSemanticsValid=false;
const proofSemanticsValid=allDirectProofsValid&&levelProofSemanticsValid;

const p002=upstreamProof("P0-02"), p006=upstreamProof("P0-06");
let predecessorRulesValid=true;
if(level==="C0") predecessorRulesValid=proofSemanticsValid;
else if(level==="C1") predecessorRulesValid=chainValid("C0")&&directProofValid("LAB_REPORT")&&Boolean(p002);
else if(level==="C2") predecessorRulesValid=chainValid("C0")&&chainValid("C1")&&Boolean(pkg.project_binding?.project_id)&&Boolean(pkg.project_binding?.instance_id)&&Boolean(p006)&&directProofValid("FAT_SAT_EVIDENCE");
else if(level==="C3"){
  const start=parseUtc(pkg.continuous_monitoring?.window_start),end=parseUtc(pkg.continuous_monitoring?.window_end),days=Number.isFinite(start)&&Number.isFinite(end)?(end-start)/86400000:-1;
  const requiredDays=pkg.continuous_monitoring?.required_days;
  predecessorRulesValid=chainValid("C0")&&chainValid("C1")&&chainValid("C2")&&Boolean(pkg.project_binding?.project_id)&&Boolean(pkg.project_binding?.instance_id)&&Boolean(p006)&&Number.isInteger(requiredDays)&&requiredDays>=1&&end>start&&pkg.continuous_monitoring?.coverage_ratio===1.0&&days>=requiredDays&&directProofValid("CONTINUOUS_EVIDENCE")&&directProofValid("FAT_SAT_EVIDENCE");
}else predecessorRulesValid=false;

const baseline=pkg.baseline??{}, observed=pkg.observed_baseline??{};
let baselineBindingsValid=MATERIAL_KEYS.every(k=>baseline[k]!==undefined&&baseline[k]!==""&&observed[k]!==undefined&&observed[k]!=="");
if(levelIndex>=1) baselineBindingsValid=baselineBindingsValid&&Boolean(p002);
if(levelIndex>=2) baselineBindingsValid=baselineBindingsValid&&Boolean(p006);
const continuousDriftProof=directProof("CONTINUOUS_EVIDENCE");
const materialDrift=MATERIAL_KEYS.some(k=>baseline[k]!==observed[k])||(pkg.drifts??[]).some(r=>r.material===true&&r.status!=="CLOSED")||(continuousDriftProof?.proof.material_open_drifts??0)>0;
const driftDeclarationValid=pkg.declared_material_drift===materialDrift;

const now=parseUtc(pkg.assessment_time),from=parseUtc(pkg.validity?.valid_from),until=parseUtc(pkg.validity?.valid_until);
const expired=!Number.isFinite(now)||!Number.isFinite(until)||now>until, notYet=!Number.isFinite(now)||!Number.isFinite(from)||now<from;
const revoked=pkg.validity?.revoked===true, superseded=pkg.validity?.superseded===true;
let lifecycleState=revoked?"REVOKED":superseded?"SUPERSEDED":expired?"EXPIRED":materialDrift?"REEVALUATION_REQUIRED":"VALID";
const reevaluationExpected=(materialDrift||expired||revoked||superseded)?"REQUIRED":"NOT_REQUIRED";
const reevaluationValid=pkg.claimed_reevaluation_state===reevaluationExpected;
const validityFieldsValid=!notYet&&!expired&&!revoked&&!superseded;

const outcomeStates=outcomes.map(r=>r.result).filter(result=>result!=="NOT_APPLICABLE");
const overallDecision=outcomeStates.includes("FAIL")?"FAIL":outcomeStates.includes("BLOCKED")?"BLOCKED":outcomeStates.length>0?"PASS":"NOT_APPLICABLE";
const overallDecisionValid=outcomesValid&&pkg.declared_decision===overallDecision&&!("weighted_score" in pkg);

function metricVector(){
  const out={},passCount=outcomes.filter(r=>r.result==="PASS").length;
  const directPairs=new Map(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST","LAB_REPORT","FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE"].map(type=>[type,directProof(type)]));
  const semanticIds=new Set([...directPairs.values()].filter(Boolean).map(pair=>pair.ref.evidence_id));
  const p002Ids=new Set(p002?refs.filter(ref=>ref.source_stage===UPSTREAM["P0-02"].stage).map(ref=>ref.evidence_id):[]);
  const p006Ids=new Set(p006?refs.filter(ref=>ref.source_stage===UPSTREAM["P0-06"].stage).map(ref=>ref.evidence_id):[]);
  for(const id of [...p002Ids,...p006Ids]) semanticIds.add(id);
  const p002Status=p002?upstreamStatus("P0-02"):null;
  const targets=Array.isArray(p002Status?.targets)?p002Status.targets:[];
  const crossN=targets.filter(target=>target&&typeof target==="object"&&target.required_failures===0).length;
  const crossD=targets.length;
  const regression=p002Status?.regression??{};
  const regressionSignals=p002Status?[p002Status.status==="PASS",typeof regression.embedded_reference==="string"&&regression.embedded_reference.endsWith("PASS"),regression.archive_pipeline==="PASS"]:[];
  const regressionN=regressionSignals.filter(Boolean).length,regressionD=regressionSignals.length;
  const continuous=directPairs.get("CONTINUOUS_EVIDENCE");
  let driftN=0,driftD=0;
  if(level==="C3"&&continuous){
    const closed=continuous.proof.closed_drifts,opened=continuous.proof.material_open_drifts;
    if(Number.isInteger(closed)&&closed>=0&&Number.isInteger(opened)&&opened>=0){driftN=closed;driftD=closed+opened;}
    else{driftN=-1;driftD=-1;}
  }
  const expected={
    machine_readable_coverage:[(profile.proof_types??[]).filter(type=>PROOF_TYPES.has(type)).length,PROOF_TYPES.size],
    requirement_testability:[new Set(criteria.map(row=>row.test_id).filter(id=>/^CAE-T(?:00[1-9]|01[0-9]|020)$/.test(id))).size,20],
    automation_rate:[expectedAutomatable,expectedAutomatable],
    evidence_completeness:[validEvidenceIds.size,evidenceIds.size],
    applicable_required_pass_rate:[passCount,outcomes.length],
    cross_implementation_reproducibility:[crossN,crossD],
    regression_stability:[regressionN,regressionD],
    c3_drift_closure_rate:[driftN,driftD],
  };
  for(const name of METRICS){
    const row=pkg.effectiveness_sources?.[name]??{}, n=row.numerator,d=row.denominator,src=row.source_evidence_ids;
    let ok=Number.isInteger(n)&&Number.isInteger(d)&&n>=0&&d>=0&&n<=d&&n===expected[name][0]&&d===expected[name][1]&&Array.isArray(src)&&src.length>0&&new Set(src).size===src.length&&src.every(id=>validEvidenceIds.has(id));
    if(name==="evidence_completeness") ok=ok&&src.length===evidenceIds.size&&src.every(id=>evidenceIds.has(id));
    else ok=ok&&src.every(id=>semanticIds.has(id));
    if(["cross_implementation_reproducibility","regression_stability"].includes(name)&&p002) ok=ok&&src.every(id=>p002Ids.has(id));
    if(name==="c3_drift_closure_rate"&&level==="C3") ok=ok&&Boolean(continuous)&&src.includes(continuous.ref.evidence_id);
    out[name]={numerator:n,denominator:d,source_evidence_ids:src,status:ok?(d===0?"NOT_APPLICABLE":"MEASURED"):"INVALID",value:ok&&d!==0?n/d:null};
  }
  return out;
}
const metrics=metricVector();
const metricsValid=deepEqual(metrics,pkg.claimed_effectiveness_metrics??{})&&Object.values(metrics).every(r=>r.status!=="INVALID");

const traceRows=pkg.trace_bindings??[],bindings=new Map(traceRows.map(r=>[r.test_id,r]));
const directTraceByType=new Map(["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST","LAB_REPORT","FAT_SAT_EVIDENCE","CONTINUOUS_EVIDENCE"].map(type=>[type,directProof(type)]));
const semanticTraceIds=new Set([...directTraceByType.values()].filter(Boolean).map(pair=>pair.ref.evidence_id));
const p002TraceIds=new Set(p002?refs.filter(ref=>ref.source_stage===UPSTREAM["P0-02"].stage).map(ref=>ref.evidence_id):[]);
const p006TraceIds=new Set(p006?refs.filter(ref=>ref.source_stage===UPSTREAM["P0-06"].stage).map(ref=>ref.evidence_id):[]);
for(const id of [...p002TraceIds,...p006TraceIds]) semanticTraceIds.add(id);
const chainIds=new Map(["C0","C1","C2"].map(chainLevel=>[chainLevel,new Set(chainValid(chainLevel)?(pkg.assurance_chain??[]).filter(row=>row.level===chainLevel).map(row=>row.evidence_id):[])]));
const sourceSet=type=>{const pair=directTraceByType.get(type);return new Set(pair?[pair.ref.evidence_id]:[]);};
const tokenSources=new Map([
  ["MODEL",sourceSet("MODEL")],["PROFILE_DECLARATION",sourceSet("PROFILE_DECLARATION")],["AUTOMATED_TEST",sourceSet("AUTOMATED_TEST")],
  ["LAB_REPORT",sourceSet("LAB_REPORT").size>0?sourceSet("LAB_REPORT"):chainIds.get("C1")],["FAT_SAT_EVIDENCE",sourceSet("FAT_SAT_EVIDENCE")],["CONTINUOUS_EVIDENCE",sourceSet("CONTINUOUS_EVIDENCE")],
  ["C0_PREDECESSOR",chainIds.get("C0")],["C1_PREDECESSOR",chainIds.get("C1")],["C2_PREDECESSOR",chainIds.get("C2")],
  ["PROJECT_BINDING",sourceSet("FAT_SAT_EVIDENCE")],["P0_06_EVIDENCE",p006TraceIds],
]);
const criterionApplies=criterion=>criterion.applicability_rule==="ALL"||(criterion.applicability_rule==="C0_RULE"&&level==="C0")||(criterion.applicability_rule==="LEVEL_GTE_C1"&&levelIndex>=1)||(criterion.applicability_rule==="LEVEL_GTE_C2"&&levelIndex>=2)||(criterion.applicability_rule==="C3"&&level==="C3");
let traceValid=traceRows.length===20&&bindings.size===20;
for(const criterion of criteria){
  if(!traceValid) break;
  const b=bindings.get(criterion.test_id),ids=b?.evidence_ids??[],directPair=directTraceByType.get(criterion.proof_type);
  const requiredIds=directPair?new Set([directPair.ref.evidence_id]):semanticTraceIds;
  const requiredSets=[requiredIds];
  if(criterionApplies(criterion)) for(const token of criterion.evidence_requirements??[]) requiredSets.push(tokenSources.get(String(token))??semanticTraceIds);
  if(!b||b.requirement_id!==criterion.requirement_id||!Array.isArray(ids)||ids.length===0||new Set(ids).size!==ids.length||ids.some(id=>!validEvidenceIds.has(id))||requiredSets.some(required=>required.size===0||!ids.some(id=>required.has(id)))) traceValid=false;
}
const statementValid=pkg.certification_claim===false&&pkg.statement_type==="CONFORMITY_EVALUATION_STATEMENT"&&pkg.statement_scope?.assessment_object_id===pkg.assessment_object?.object_id&&pkg.statement_scope?.assessment_level===level&&pkg.statement_scope?.profile_id===pkg.profile?.id&&pkg.statement_scope?.profile_version===pkg.profile?.version&&pkg.signature_state==="UNSIGNED"&&!pkg.signature;
const evidenceChecks=new Map([
  ["CAE-R001",identityValid],["CAE-R002",registryValid],["CAE-R003",evidenceHashesValid],["CAE-R004",proofSetValid&&proofSemanticsValid],
  ["CAE-R005",automationValid],["CAE-R006",roleValid],["CAE-R007",naValid],["CAE-R008",exceptionValid],
  ["CAE-R009",level!=="C0"||["MODEL","PROFILE_DECLARATION","AUTOMATED_TEST"].every(directProofValid)],
  ["CAE-R010",levelIndex<1||predecessorRulesValid],["CAE-R011",levelIndex<2||predecessorRulesValid],["CAE-R012",level!=="C3"||predecessorRulesValid],
  ["CAE-R013",baselineBindingsValid],["CAE-R014",driftDeclarationValid],["CAE-R015",reevaluationValid],["CAE-R016",validityFieldsValid],
  ["CAE-R018",metricsValid],["CAE-R019",traceValid],["CAE-R020",statementValid],
]);
const evidenceOutcomesValid=[...evidenceChecks].every(([requirementId,passed])=>(outcomeMap.get(requirementId)==="PASS")===Boolean(passed));
const outcomesContractValid=outcomesValid&&evidenceOutcomesValid;

const valid=identityValid&&registryValid&&evidenceHashesValid&&proofSetValid&&proofSemanticsValid&&roleValid&&automationValid&&naValid&&exceptionValid&&predecessorRulesValid&&baselineBindingsValid&&driftDeclarationValid&&reevaluationValid&&validityFieldsValid&&overallDecisionValid&&outcomesContractValid&&metricsValid&&traceValid&&statementValid;
console.log(JSON.stringify({valid,overall_decision:overallDecision,lifecycle_state:lifecycleState,schema_valid:packageSchemaValid,registry_valid:registryValid,evidence_hashes_valid:evidenceHashesValid,metrics_valid:metricsValid,predecessor_rules_valid:predecessorRulesValid,baseline_bindings_valid:baselineBindingsValid,drift_declaration_valid:driftDeclarationValid,reevaluation_valid:reevaluationValid,role_valid:roleValid,proof_set_valid:proofSetValid,proof_semantics_valid:proofSemanticsValid,automation_valid:automationValid,outcomes_valid:outcomesContractValid,trace_valid:traceValid,statement_valid:statementValid,certification_claim:pkg.certification_claim===true}));
process.exit(valid?0:1);
