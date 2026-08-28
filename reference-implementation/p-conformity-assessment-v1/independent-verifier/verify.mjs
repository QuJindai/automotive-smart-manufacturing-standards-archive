#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const packageDir = process.argv[2];
if (!packageDir) {
  console.error("usage: node verify.mjs <package-dir>");
  process.exit(2);
}

const LEVEL_ORDER = {C0: 0, C1: 1, C2: 2, C3: 3};
const ROLE_BY_LEVEL = {
  C0: "SUPPLIER_DECLARANT",
  C1: "LAB_EVALUATOR",
  C2: "FAT_SAT_EVALUATOR",
  C3: "OPERATIONS_MONITOR",
};
const REQUIRED_PROOFS = {
  C0: new Set(["MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"]),
  C1: new Set(["MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST", "LAB_REPORT"]),
  C2: new Set(["AUTOMATED_TEST", "LAB_REPORT", "FAT_SAT_EVIDENCE"]),
  C3: new Set(["AUTOMATED_TEST", "FAT_SAT_EVIDENCE", "CONTINUOUS_EVIDENCE"]),
};
const MATERIAL_KEYS = ["profile_version", "program_version", "parameter_hash", "interface_version"];
const METRIC_NAMES = [
  "machine_readable_coverage",
  "requirement_testability",
  "automation_rate",
  "evidence_completeness",
  "applicable_required_pass_rate",
  "cross_implementation_reproducibility",
  "regression_stability",
  "c3_drift_closure_rate",
];

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function safeUri(uri) {
  return typeof uri === "string" && uri.length > 0 && !uri.includes("://") && !path.isAbsolute(uri) && !uri.split(/[\\/]+/).includes("..");
}

function metricVector(sources) {
  const out = {};
  for (const name of METRIC_NAMES) {
    const row = sources?.[name] ?? {};
    const numerator = row.numerator;
    const denominator = row.denominator;
    const valid = Number.isInteger(numerator) && Number.isInteger(denominator) && numerator >= 0 && denominator >= 0 && numerator <= denominator;
    if (!valid) out[name] = {numerator, denominator, status: "INVALID", value: null};
    else if (denominator === 0) out[name] = {numerator, denominator, status: "NOT_APPLICABLE", value: null};
    else out[name] = {numerator, denominator, status: "MEASURED", value: numerator / denominator};
  }
  return out;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function chainHas(pkg, level) {
  return (pkg.assurance_chain ?? []).some(row => row.level === level && row.decision === "PASS" && row.lifecycle_state === "VALID");
}

function hasSourceStage(pkg, stage) {
  return (pkg.evidence_refs ?? []).some(row => row.source_stage === stage);
}

function proofTypes(pkg) {
  return new Set((pkg.evidence_refs ?? []).map(row => String(row.proof_type)));
}

function parseUtc(value) {
  if (typeof value !== "string" || !value.endsWith("Z")) return NaN;
  return Date.parse(value);
}

let pkg;
try {
  pkg = JSON.parse(fs.readFileSync(path.join(packageDir, "package.json"), "utf8"));
} catch (err) {
  console.log(JSON.stringify({valid: false, error: String(err)}));
  process.exit(1);
}

let evidenceHashesValid = Array.isArray(pkg.evidence_refs) && pkg.evidence_refs.length > 0;
for (const ref of pkg.evidence_refs ?? []) {
  if (!safeUri(ref.uri)) {
    evidenceHashesValid = false;
    continue;
  }
  try {
    const data = fs.readFileSync(path.join(packageDir, ref.uri));
    if (data.length !== Number(ref.size_bytes) || sha256(data) !== ref.sha256) evidenceHashesValid = false;
  } catch {
    evidenceHashesValid = false;
  }
}

const metrics = metricVector(pkg.effectiveness_sources ?? {});
const metricsValid = deepEqual(metrics, pkg.claimed_effectiveness_metrics ?? {}) && Object.values(metrics).every(row => row.status !== "INVALID");

const level = pkg.assessment_level;
const roleValid = ROLE_BY_LEVEL[level] === pkg.assessor?.role && typeof pkg.assessor?.assessor_id === "string" && pkg.assessor.assessor_id.length > 0;
const types = proofTypes(pkg);
const requiredProofs = REQUIRED_PROOFS[level] ?? new Set();
const proofSetValid = [...requiredProofs].every(item => types.has(item));

const execution = pkg.execution_summary ?? {};
const automationValid = execution.manual_passed_automatable === 0 && execution.automatable_required === execution.automated_executed && (pkg.evidence_refs ?? []).filter(row => row.proof_type === "AUTOMATED_TEST").every(row => row.execution_mode === "AUTOMATED");
const naValid = (pkg.not_applicable ?? []).every(row => row.permitted === true && typeof row.justification === "string" && row.justification.length > 0);
const exceptionValid = (pkg.exceptions ?? []).every(row => row.masks_required_failure !== true);

let predecessorRulesValid = true;
if (level === "C0") {
  predecessorRulesValid = ["MODEL", "PROFILE_DECLARATION", "AUTOMATED_TEST"].every(item => types.has(item));
} else if (level === "C1") {
  predecessorRulesValid = chainHas(pkg, "C0") && types.has("LAB_REPORT") && hasSourceStage(pkg, "R14_P0_02_DUAL_IMPLEMENTATION_CROSS_VALIDATION");
} else if (level === "C2") {
  predecessorRulesValid = chainHas(pkg, "C0") && chainHas(pkg, "C1") && Boolean(pkg.project_binding?.project_id) && Boolean(pkg.project_binding?.instance_id) && hasSourceStage(pkg, "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE");
} else if (level === "C3") {
  const start = parseUtc(pkg.continuous_monitoring?.window_start);
  const end = parseUtc(pkg.continuous_monitoring?.window_end);
  const days = Number.isFinite(start) && Number.isFinite(end) ? (end - start) / 86400000 : -1;
  predecessorRulesValid = chainHas(pkg, "C0") && chainHas(pkg, "C1") && chainHas(pkg, "C2") && Boolean(pkg.project_binding?.project_id) && Boolean(pkg.project_binding?.instance_id) && hasSourceStage(pkg, "R14_P0_06_MANUFACTURING_EVIDENCE_CHAIN_PROTOTYPE") && pkg.continuous_monitoring?.coverage_ratio === 1.0 && days >= Number(pkg.continuous_monitoring?.required_days ?? 0) && types.has("CONTINUOUS_EVIDENCE");
} else {
  predecessorRulesValid = false;
}

const baseline = pkg.baseline ?? {};
const observed = pkg.observed_baseline ?? {};
let baselineBindingsValid = MATERIAL_KEYS.every(key => baseline[key] !== undefined && observed[key] !== undefined);
for (const ref of pkg.evidence_refs ?? []) {
  if (!ref.source_stage || !safeUri(ref.uri)) continue;
  try {
    const proof = JSON.parse(fs.readFileSync(path.join(packageDir, ref.uri), "utf8"));
    if (proof.standard_id === "P0-02" && proof.source_blob_sha !== baseline.p0_02_status_blob_sha) baselineBindingsValid = false;
    if (proof.standard_id === "P0-06" && proof.source_blob_sha !== baseline.p0_06_status_blob_sha) baselineBindingsValid = false;
  } catch {
    baselineBindingsValid = false;
  }
}

const materialDrift = MATERIAL_KEYS.some(key => baseline[key] !== observed[key]) || (pkg.drifts ?? []).some(row => row.material === true && row.status !== "CLOSED");
const driftDeclarationValid = pkg.declared_material_drift === materialDrift;

const assessmentTime = parseUtc(pkg.assessment_time);
const validFrom = parseUtc(pkg.validity?.valid_from);
const validUntil = parseUtc(pkg.validity?.valid_until);
const expired = !Number.isFinite(assessmentTime) || !Number.isFinite(validUntil) || assessmentTime > validUntil;
const notYetValid = !Number.isFinite(assessmentTime) || !Number.isFinite(validFrom) || assessmentTime < validFrom;
const revoked = pkg.validity?.revoked === true;
const superseded = pkg.validity?.superseded === true;
let lifecycleState = "VALID";
if (revoked) lifecycleState = "REVOKED";
else if (superseded) lifecycleState = "SUPERSEDED";
else if (expired) lifecycleState = "EXPIRED";
else if (materialDrift) lifecycleState = "REEVALUATION_REQUIRED";

const reevaluationExpected = (materialDrift || expired || revoked || superseded) ? "REQUIRED" : "NOT_REQUIRED";
const reevaluationValid = pkg.claimed_reevaluation_state === reevaluationExpected;
const validityFieldsValid = !notYetValid;

const outcomes = (pkg.required_outcomes ?? []).map(row => row.result);
let overallDecision = "PASS";
if (outcomes.includes("FAIL")) overallDecision = "FAIL";
else if (outcomes.includes("BLOCKED")) overallDecision = "BLOCKED";
const overallDecisionValid = outcomes.length > 0 && pkg.declared_decision === overallDecision && !("weighted_score" in pkg);

const statementValid = pkg.certification_claim === false && pkg.statement_type === "CONFORMITY_EVALUATION_STATEMENT" && ["UNSIGNED", "SIGNED_VERIFIED", "SIGNED_UNVERIFIED"].includes(pkg.signature_state) && (pkg.signature_state !== "UNSIGNED" || !pkg.signature);

const evidenceIds = new Set((pkg.evidence_refs ?? []).map(row => row.evidence_id));
const bindings = new Map((pkg.trace_bindings ?? []).map(row => [row.test_id, row]));
let traceValid = bindings.size === 20;
for (let i = 1; i <= 20 && traceValid; i++) {
  const testId = `CAE-T${String(i).padStart(3, "0")}`;
  const requirementId = `CAE-R${String(i).padStart(3, "0")}`;
  const binding = bindings.get(testId);
  if (!binding || binding.requirement_id !== requirementId || !Array.isArray(binding.evidence_ids) || binding.evidence_ids.length === 0 || binding.evidence_ids.some(id => !evidenceIds.has(id))) traceValid = false;
}

const valid = evidenceHashesValid && metricsValid && predecessorRulesValid && roleValid && proofSetValid && automationValid && naValid && exceptionValid && baselineBindingsValid && driftDeclarationValid && reevaluationValid && validityFieldsValid && overallDecisionValid && statementValid && traceValid;

console.log(JSON.stringify({
  valid,
  overall_decision: overallDecision,
  lifecycle_state: lifecycleState,
  evidence_hashes_valid: evidenceHashesValid,
  metrics_valid: metricsValid,
  predecessor_rules_valid: predecessorRulesValid,
  baseline_bindings_valid: baselineBindingsValid,
  drift_declaration_valid: driftDeclarationValid,
  reevaluation_valid: reevaluationValid,
  role_valid: roleValid,
  proof_set_valid: proofSetValid,
  automation_valid: automationValid,
  trace_valid: traceValid,
  certification_claim: pkg.certification_claim === true,
}));
process.exit(valid ? 0 : 1);
