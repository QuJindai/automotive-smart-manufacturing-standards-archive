#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const packageDir = process.argv[2];
if (!packageDir) {
  console.error("usage: node verify.mjs <package-dir>");
  process.exit(2);
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = stable(value[key]);
    return out;
  }
  return value;
}

function canonicalRecord(record) {
  const candidate = structuredClone(record);
  candidate.integrity = {...(candidate.integrity || {})};
  delete candidate.integrity.record_sha256;
  return Buffer.from(JSON.stringify(stable(candidate)), "utf8");
}

function sha256(buf) {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

function safeArtifactUri(uri) {
  if (typeof uri !== "string" || !uri || uri.includes("://") || path.isAbsolute(uri)) return false;
  return !uri.split(/[\\/]+/).includes("..");
}

let pkg;
try {
  pkg = JSON.parse(fs.readFileSync(path.join(packageDir, "package.json"), "utf8"));
} catch (err) {
  console.log(JSON.stringify({valid:false, record_hashes_valid:false, artifacts_valid:false, lineage_valid:false, release_valid:false, error:String(err)}));
  process.exit(1);
}

const records = Array.isArray(pkg.records) ? pkg.records : [];
const byId = new Map(records.map(r => [r.evidence_id, r]));
let recordHashesValid = true;
let artifactsValid = true;
let lineageValid = true;
let releaseValid = records.some(r => r?.disposition?.decision === "RELEASED");

for (const r of records) {
  if (!r?.integrity?.record_sha256 || sha256(canonicalRecord(r)) !== r.integrity.record_sha256) recordHashesValid = false;
  for (const a of (r.raw_artifacts || [])) {
    if (!safeArtifactUri(a.uri)) { artifactsValid = false; continue; }
    const target = path.join(packageDir, a.uri);
    try {
      const data = fs.readFileSync(target);
      if (data.length !== Number(a.size_bytes) || sha256(data) !== a.sha256) artifactsValid = false;
    } catch { artifactsValid = false; }
  }
  const lin = r.lineage || {};
  const parents = lin.parent_evidence_ids || [];
  if (parents.length === 0) {
    if (lin.previous_record_hash !== null && lin.previous_record_hash !== "" && lin.previous_record_hash !== undefined) lineageValid = false;
  } else if (parents.length !== 1 || !byId.has(parents[0])) {
    lineageValid = false;
  } else {
    const p = byId.get(parents[0]);
    if (lin.previous_record_hash !== p?.integrity?.record_sha256) lineageValid = false;
    const pd = p?.disposition?.decision;
    const pa = p?.lineage?.attempt_no;
    if (lin.relation === "REPAIR_OF" && !(r?.disposition?.decision === "REWORK" && ["FAIL","REWORK"].includes(pd) && lin.attempt_no === pa)) lineageValid = false;
    if (lin.relation === "RETEST_OF" && !(["PASS","FAIL"].includes(r?.disposition?.decision) && ["FAIL","REWORK"].includes(pd) && lin.attempt_no === pa + 1)) lineageValid = false;
    if (lin.relation === "RELEASES") {
      const same = r?.subject?.subject_id === p?.subject?.subject_id && r?.subject?.operation_id === p?.subject?.operation_id;
      const ok = r?.disposition?.decision === "RELEASED" && pd === "PASS" && lin.attempt_no === pa && same;
      if (!ok) { lineageValid = false; releaseValid = false; }
    }
  }
}

const groups = new Map();
for (const r of records) {
  const key = `${r?.subject?.subject_id}|${r?.subject?.operation_id}`;
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(r);
}
for (const group of groups.values()) {
  const attempts = group.map(r => r?.lineage?.attempt_no).filter(Number.isInteger);
  if (attempts.length !== group.length || attempts.some(a => a < 1)) lineageValid = false;
  if (attempts.length) {
    const unique = [...new Set(attempts)].sort((a,b)=>a-b);
    const expected = Array.from({length: Math.max(...unique)}, (_,i)=>i+1);
    if (JSON.stringify(unique) !== JSON.stringify(expected)) lineageValid = false;
  }
}
for (const r of records.filter(r => r?.disposition?.decision === "RELEASED")) {
  const parents = r?.lineage?.parent_evidence_ids || [];
  const p = parents.length === 1 ? byId.get(parents[0]) : null;
  const same = p && r?.subject?.subject_id === p?.subject?.subject_id && r?.subject?.operation_id === p?.subject?.operation_id;
  if (!(p && p?.disposition?.decision === "PASS" && same)) releaseValid = false;
}

const valid = recordHashesValid && artifactsValid && lineageValid && releaseValid;
console.log(JSON.stringify({valid, record_hashes_valid:recordHashesValid, artifacts_valid:artifactsValid, lineage_valid:lineageValid, release_valid:releaseValid}));
process.exit(valid ? 0 : 1);
