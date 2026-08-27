# P0-06 Manufacturing Evidence Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the P-ME V1 manufacturing evidence-chain executable prototype with an EOL Detection Profile, tamper/lineage testing, standardized evidence outputs and an independent Node.js verifier.

**Architecture:** A standard-library Python reference implementation validates a machine-readable P-ME package, derives its trace graph and emits validator evidence. A separate dependency-free Node.js verifier independently checks canonical hashes and core lineage rules. Static synthetic EOL fixtures reuse the frozen P0-02 EOL station identity but do not depend on the P0-02 runtime.

**Tech Stack:** JSON / JSON Schema assets, Python 3 standard library, Node.js standard library, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-p0-06-manufacturing-evidence-chain-design.md`

## Global Constraints

- Preserve frozen P0-02 behavior and regression gates.
- No real VIN, employee identity, private Drive URL, token or secret in fixtures/evidence.
- No third-party Python or Node dependencies.
- `certification_claim=false` in all validator evidence.
- SHA-256 is used only for integrity/tamper detection; no legal non-repudiation claim.
- EOL is the only process Profile implemented in this slice; core evidence semantics remain process-neutral.

---

### Task 1: Machine-readable P-ME assets and structural validator

**Files:**
- Create: `machine-readable/p0-06/manufacturing-evidence-v1.schema.json`
- Create: `machine-readable/p0-06/eol-profile-v1.json`
- Create: `machine-readable/p0-06/conformance-criteria-v1.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/pme/__init__.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/pme/validator.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/tests/test_validator.py`

**Interfaces:**
- Produces: `validate_package(package_dir: pathlib.Path) -> ValidationRun`.
- `ValidationRun.results` contains one result for each `ME-T001..ME-T018` with `PASS|FAIL|BLOCKED`.

- [ ] Write failing tests for required package identity, unique evidence ids, provenance, object linkage, version binding, timestamps, measurement fields and uncertainty declaration.
- [ ] Run `PYTHONPATH=. python -m unittest discover -s tests -v`; confirm failures are due to missing validator/assets.
- [ ] Implement the minimum structural validator and stable test-result dataclasses.
- [ ] Re-run the full Task 1 suite until green.
- [ ] Commit the Task 1 deliverable.

### Task 2: Canonical hashing, raw-artifact integrity and Golden EOL packages

**Files:**
- Create: `reference-implementation/p-manufacturing-evidence-v1/pme/canonical.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-single-pass/package.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-single-pass/raw/eol-result.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-rework-retest/package.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-rework-retest/raw/attempt-1.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-rework-retest/raw/repair.json`
- Create: `reference-implementation/p-manufacturing-evidence-v1/examples/eol-rework-retest/raw/attempt-2.json`
- Modify: `reference-implementation/p-manufacturing-evidence-v1/pme/validator.py`
- Test: `reference-implementation/p-manufacturing-evidence-v1/tests/test_integrity.py`

**Interfaces:**
- Produces: `canonical_record_bytes(record) -> bytes`, `record_sha256(record) -> str`, `file_sha256(path) -> str`.

- [ ] Write failing tests for `ME-T009` raw artifact hash/size and `ME-T010` canonical record hash.
- [ ] Verify RED.
- [ ] Implement deterministic UTF-8 JSON canonicalization with sorted keys and compact separators, excluding only `integrity.record_sha256` from the record hash input.
- [ ] Add two fully synthetic Golden EOL packages with correct record and artifact hashes.
- [ ] Verify both Golden packages pass Tasks 1-2 checks.
- [ ] Commit the Task 2 deliverable.

### Task 3: Lineage, trace graph, release trace query and negative-case registry

**Files:**
- Create: `reference-implementation/p-manufacturing-evidence-v1/pme/trace.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/fixtures/negative-cases.json`
- Modify: `reference-implementation/p-manufacturing-evidence-v1/pme/validator.py`
- Test: `reference-implementation/p-manufacturing-evidence-v1/tests/test_lineage.py`
- Test: `reference-implementation/p-manufacturing-evidence-v1/tests/test_negative_cases.py`

**Interfaces:**
- Produces: `build_trace_graph(package) -> dict`, `trace_release(graph, evidence_id) -> dict`.

- [ ] Write failing tests for parent resolution, previous hash, contiguous attempts, legal RETEST/REPAIR relations, legal RELEASED predecessor, mandatory trace edges and release-to-source traceability.
- [ ] Add mutation cases for missing provenance, broken subject linkage, timestamp inversion, program/version mismatch, parameter hash mismatch, missing artifact, artifact tamper, record tamper, broken parent hash, duplicate id, attempt gap and illegal release.
- [ ] Verify RED on intended conformance ids.
- [ ] Implement lineage and trace rules; each mutation must fail its intended required test without false PASS.
- [ ] Commit the Task 3 deliverable.

### Task 4: Standardized validator evidence and independent Node verifier

**Files:**
- Create: `reference-implementation/p-manufacturing-evidence-v1/pme/output.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/run_reference.py`
- Create: `reference-implementation/p-manufacturing-evidence-v1/independent-verifier/verify.mjs`
- Test: `reference-implementation/p-manufacturing-evidence-v1/tests/test_output.py`
- Test: `reference-implementation/p-manufacturing-evidence-v1/tests/test_cross_implementation.py`

**Interfaces:**
- CLI: `python run_reference.py --package <dir> --out <dir>` prints `ME_REQUIRED_FAILURES=<n>`.
- Node CLI: `node independent-verifier/verify.mjs <package-dir>` prints JSON containing `valid`, `record_hashes_valid`, `lineage_valid`, `release_valid`.

- [ ] Write failing output and cross-implementation tests.
- [ ] Verify RED.
- [ ] Implement the six standardized output files and set `certification_claim=false`.
- [ ] Implement Node canonicalization/hash/lineage checks without invoking Python.
- [ ] Require Python/Node agreement on both Golden packages and selected record/artifact/lineage tamper cases.
- [ ] Commit the Task 4 deliverable.

### Task 5: CI gate, P0-02 regression and frozen evidence artifact

**Files:**
- Create: `.github/workflows/validate-p0-06-manufacturing-evidence.yml`
- Create: `reference-implementation/p-manufacturing-evidence-v1/README.md`
- Create after verified run: `archive/p0-06-manufacturing-evidence-status.json`

**Interfaces:**
- CI artifact contains both Golden validation outputs, cross-implementation result, negative-case summary and test logs.

- [ ] Run the full Python suite and both Golden CLIs in CI.
- [ ] Run the independent Node verifier against both Golden packages and selected negative packages.
- [ ] Assert `ME_REQUIRED_FAILURES=0`, `PASS=18`, `FAIL=0`, `BLOCKED=0` for both Golden packages.
- [ ] Re-run existing P0-02 BaSyx/FA3ST and V1 19/19 workflows through PR path changes or explicit regression job.
- [ ] Upload one-day evidence artifact and capture its provider SHA-256 digest.
- [ ] Recover the artifact, independently verify SHA-256 and ZIP integrity, scan for private Drive URLs/real identifiers.
- [ ] Write machine-readable frozen status only after all gates pass.
- [ ] Merge with expected head SHA, verify main push CI, archive main artifact to Drive, read it back and independently revalidate bytes/hash.
