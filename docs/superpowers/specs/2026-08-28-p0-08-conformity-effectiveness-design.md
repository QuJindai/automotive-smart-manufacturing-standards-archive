# R14 P0-08 Conformity Assessment & Implementation Effectiveness — Design

## 1. Goal and frozen scope

Build the executable prototype for **P0-08 汽车智能制造 标准实施效果与符合性评价方法** on top of the frozen R14 P0-02 and P0-06 baselines.

The product is **P-CAE V1 (Conformity Assessment & Effectiveness V1)**. Its first Automotive Profile is **P-CAE-AUTO-R14 1.0**, evaluating the frozen P0-02 equipment-capability evidence and P0-06 manufacturing-evidence chain through one common C0-C3 assessment framework.

P0-08 MUST NOT re-run or duplicate the P0-02 AAS adapter tests or the P0-06 P-ME validator. Those remain upstream proof providers. P0-08 validates proof identity, hash, applicability, level prerequisites, evaluation semantics, validity and lifecycle state.

P0-08 is an **evaluation method and orchestration model**, not a certification scheme, licensing regime, membership gate or legal trust service.

## 2. Core assessment chain

The normative chain is:

`Requirement -> Proof -> Test -> Evidence -> Assessment`

Every required assessment criterion MUST bind:

- `requirement_id`
- `proof_type`
- `test_id`
- `automation_flag`
- `required`
- `applicability_rule`
- `decision_rule`
- `evidence_requirements`

No required `FAIL` may be offset by a score, average, exception or unrelated PASS. A required `BLOCKED` is not a PASS. `NOT_APPLICABLE` is legal only when the criterion explicitly permits it and a machine-readable justification is present.

## 3. C0-C3 levels

### C0 — Supplier Declaration

Object: development/tender-stage implementation declaration.

Required evidence includes machine-readable model/profile identity, version/baseline, validator result and declared deviations. Role: `SUPPLIER_DECLARANT`.

### C1 — Laboratory Conformance

Object: product/software implementation version.

Requires a valid C0 predecessor plus execution of applicable CAC/Test Kit criteria by `LAB_EVALUATOR`. It may consume upstream P0-02 dual-implementation evidence. C1 does not itself create an accredited certification claim.

### C2 — FAT/SAT Project Conformance

Object: a concrete equipment/system instance, software version, engineering configuration and plant/project context.

Requires a valid C1 predecessor, explicit project/instance binding and project evidence. It MUST consume P0-06 manufacturing evidence where the assessed standard requires process-quality traceability. Role: `FAT_SAT_EVALUATOR`.

### C3 — Continuous Production Conformance

Object: production-running equipment/system over an observation window.

Requires a valid C2 predecessor, continuous evidence coverage and drift evaluation for software, parameters, Profile, interface and evidence completeness. Material drift MUST produce `REEVALUATION_REQUIRED` until the affected scope is re-evaluated. Role: `OPERATIONS_MONITOR`.

## 4. Machine-readable model

P-CAE V1 assessment packages contain:

- assessment/package identity and P-CAE profile version;
- `assessment_level`: C0/C1/C2/C3;
- deterministic `assessment_time` used instead of wall-clock time for reproducible evaluation;
- assessor role and synthetic/reference identity;
- assessment object and baseline fingerprint;
- predecessor assessment reference where required;
- criterion registry snapshot;
- proof/evidence references with URI, media type, size and SHA-256;
- test result records using PASS/FAIL/BLOCKED/NOT_APPLICABLE;
- exception/deviation records;
- validity/effectivity data;
- drift observations;
- implementation-effectiveness source counters.

All file references are relative package URIs. Fixtures must not include real VIN, employee identity, private Drive/Docs URLs, secrets or tokens.

## 5. Proof types

P-CAE V1 defines these proof types:

- `MODEL`
- `PROFILE_DECLARATION`
- `AUTOMATED_TEST`
- `LAB_REPORT`
- `FAT_SAT_EVIDENCE`
- `CONTINUOUS_EVIDENCE`
- `ATTESTATION`
- `EXCEPTION_RECORD`

Proof type does not determine trust level by itself; the assessment level, evaluator role, criterion and evidence binding determine whether the proof is sufficient.

## 6. Twenty required conformance tests

P-CAE V1 defines `CAE-T001..CAE-T020`:

- `CAE-T001` assessment/package/schema/profile identity is complete.
- `CAE-T002` criterion and requirement identifiers are unique and every criterion binds Requirement/Proof/Test/Automation/Decision/Evidence fields.
- `CAE-T003` every referenced proof/evidence file resolves and size/SHA-256 matches.
- `CAE-T004` proof types are valid and required evidence types are present for each applicable criterion.
- `CAE-T005` automation flags are consistent with executable test-result evidence; automatable required criteria cannot be silently manual-PASSed.
- `CAE-T006` assessor role is permitted for the declared C0-C3 assessment level.
- `CAE-T007` NOT_APPLICABLE is permitted only by criterion applicability and carries a machine-readable justification.
- `CAE-T008` exceptions/deviations cannot convert or hide a required FAIL/BLOCKED result.
- `CAE-T009` C0 mandatory supplier-declaration inputs are complete.
- `CAE-T010` C1 has a valid C0 predecessor and laboratory/TCK evidence for applicable required criteria.
- `CAE-T011` C2 has a valid C1 predecessor, project/instance binding and required FAT/SAT evidence including P0-06 proof when traceability applies.
- `CAE-T012` C3 has a valid C2 predecessor, observation-window coverage and continuous evidence inputs.
- `CAE-T013` assessed object versions, Profile, program/parameter baseline and proof baseline are consistently bound.
- `CAE-T014` material version/Profile/program/parameter/interface drift is detected.
- `CAE-T015` reevaluation state is triggered deterministically by material drift, expiry, revocation or affected baseline change.
- `CAE-T016` validity period, effectivity, revocation and supersession rules are internally consistent.
- `CAE-T017` overall assessment decision is deterministic from required criterion states and does not use a weighted aggregate score.
- `CAE-T018` implementation-effectiveness metrics are exactly reproducible from source counters and evidence states.
- `CAE-T019` final assessment can trace each required criterion to Requirement -> Test -> Proof/Evidence and upstream P0-02/P0-06 evidence when used.
- `CAE-T020` conformity statement is truthful: `certification_claim=false`; signature/trust state is explicit and no unsigned result is presented as certified.

All 20 tests are required for the P-CAE-AUTO-R14 prototype.

## 7. Overall decisions and lifecycle states

Allowed overall decisions:

- `PASS`
- `FAIL`
- `BLOCKED`
- `NOT_APPLICABLE` only for an assessment explicitly declared out-of-scope by the Profile; this is not used for the four Golden packages.

Allowed lifecycle states:

- `VALID`
- `REEVALUATION_REQUIRED`
- `EXPIRED`
- `REVOKED`
- `SUPERSEDED`

Decision precedence for applicable required criteria is `FAIL > BLOCKED > PASS`. A PASS assessment may still have lifecycle state `REEVALUATION_REQUIRED` after a subsequent material drift observation; it is then not currently valid for reuse at the affected downstream level.

## 8. Implementation-effectiveness vector

P-CAE MUST NOT produce one weighted score. It emits a metric vector with numerator, denominator, value and source references for:

1. `machine_readable_coverage`
2. `requirement_testability`
3. `automation_rate`
4. `evidence_completeness`
5. `applicable_required_pass_rate`
6. `cross_implementation_reproducibility`
7. `regression_stability`
8. `c3_drift_closure_rate`

A metric with no meaningful denominator is `NOT_APPLICABLE`, not zero and not silently omitted.

## 9. Golden packages

The Test Kit must contain four deterministic Golden packages:

- C0 supplier declaration — PASS / VALID.
- C1 laboratory conformance — PASS / VALID and bound to C0.
- C2 FAT/SAT project conformance — PASS / VALID, bound to C1 and P0-06 manufacturing evidence.
- C3 continuous conformance — PASS / VALID, bound to C2, with a closed non-material drift example and complete observation window.

Each package contains immutable snapshots of the upstream P0-02/P0-06 machine-readable status/evidence needed for that level. P0-08 validates those snapshots and hashes but does not reproduce their internal test engines.

## 10. Negative / lifecycle cases

The Test Kit must include at least these negative or lifecycle cases:

- missing proof file;
- proof SHA mismatch;
- invalid assessor role;
- manual PASS for automatable required criterion;
- illegal NOT_APPLICABLE;
- exception masking required FAIL;
- missing C0 predecessor at C1;
- missing C1 predecessor/project binding at C2;
- missing P0-06 traceability proof at C2 when required;
- insufficient C3 observation coverage;
- material parameter/Profile/interface drift;
- stale/expired assessment;
- revoked predecessor;
- upstream baseline hash mismatch;
- tampered effectiveness metric;
- unsigned result presented as certified.

Each case must fail its intended `CAE-Tnnn` or produce the intended lifecycle state without false PASS.

## 11. Standard outputs

Every validation writes:

- `assessment-summary.json`
- `criteria-results.json`
- `effectiveness-metrics.json`
- `evidence-trace.json`
- `reevaluation-state.json`
- `conformity-statement.json`
- `validator-evidence.json`

`validator-evidence.json` reuses `machine-readable/v1/evidence.schema.json`, extended compatibly only as needed to admit the `CAE-Tnnn` namespace.

`conformity-statement.json` is an evaluation statement, not a certificate, and MUST include:

- `certification_claim=false`
- `signature_state=UNSIGNED|SIGNED_VERIFIED|SIGNED_UNVERIFIED`
- assessment level, decision, lifecycle state and validity scope.

The prototype does not implement an external PKI or accredited CAB.

## 12. Independent implementation check

The reference engine is Python standard-library only. A separate dependency-free Node.js verifier independently recalculates evidence hashes, required-result aggregation, level predecessor rules, drift/lifecycle rules and effectiveness metrics. It must not invoke/import Python.

## 13. Freeze gate

P0-08 may be frozen only when, on the same mainline commit:

1. all Python unit/integration tests pass;
2. all four C0-C3 Golden packages pass `CAE-T001..CAE-T020` with required failures 0;
3. negative/lifecycle registry has zero false PASS;
4. independent Node verifier agrees on all four Goldens and selected failure/drift cases;
5. P0-02 and P0-06 upstream status/evidence snapshots are hash-bound and traceable;
6. existing P0-02/P0-06 regression workflows remain green when the common Evidence Schema is changed;
7. self-contained CI artifact is recovered, ZIP-integrity checked and SHA-256 independently revalidated;
8. evidence contains no private Drive URLs, secrets or real production identifiers;
9. final main artifact is archived to project Drive, read back and byte/hash revalidated.

## 14. Non-goals

- No weighted compliance score.
- No accredited certification claim.
- No new administrative licensing or membership regime.
- No duplicate execution of P0-02 AAS or P0-06 P-ME validators inside the P0-08 engine.
- No external PKI/CAB implementation in V1.
- No real plant/VIN/employee data in public fixtures.
