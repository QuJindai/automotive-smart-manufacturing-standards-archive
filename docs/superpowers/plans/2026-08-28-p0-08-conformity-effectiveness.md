# P0-08 Conformity Assessment & Effectiveness Implementation Plan

**Goal:** Implement and freeze P-CAE V1 / P-CAE-AUTO-R14 1.0 as a common C0-C3 assessment orchestration layer over frozen P0-02 and P0-06 evidence.

**Architecture:** Python standard-library reference evaluator + dependency-free Node verifier. P0-08 consumes immutable upstream proof snapshots, validates their hashes and applicability, evaluates CAC/level/lifecycle rules, recalculates effectiveness metrics and emits standardized evidence. It never calls the P0-02/P0-06 test engines.

**Spec:** `docs/superpowers/specs/2026-08-28-p0-08-conformity-effectiveness-design.md`

## Constraints

- Preserve `main@0ec6f5fb83614c3f75a7fe3e0a20bd197784ccf4` as frozen P0-06 baseline.
- Preserve frozen P0-02 semantics; no duplicate AAS/P-ME execution in P0-08.
- TDD: production implementation only after an observed RED failure.
- No weighted compliance score.
- No certification claim, external PKI or CAB implementation.
- Public fixtures use only synthetic/reference identities and relative evidence URIs.

## Task 1 — RED contract and machine-readable assessment surface

Create failing tests first for:

- four C0-C3 Golden CLI contracts;
- `CAE-T001..CAE-T020` presence and result surface;
- deterministic overall decision precedence;
- level-role and predecessor semantics;
- evidence SHA/size resolution;
- metric-vector recomputation;
- truthful conformity statement.

Add a PR workflow that initially only runs the tests. Open a draft PR and confirm RED is caused by missing P-CAE implementation/assets.

## Task 2 — Machine-readable model + C0 reference evaluator

Create:

- `machine-readable/p0-08/conformity-assessment-v1.schema.json`
- `machine-readable/p0-08/automotive-profile-v1.json`
- `machine-readable/p0-08/conformance-criteria-v1.json`
- Python evaluator package skeleton.

Implement only enough for C0 Golden to reach 20/20.

## Task 3 — C1/C2/C3 prerequisite and lifecycle semantics

Add C1, C2 and C3 Goldens. Implement predecessor validity, project binding, P0-06 proof requirement, observation window, version/effectivity and drift/reevaluation logic.

## Task 4 — Negative/lifecycle registry

Implement at least 16 registered cases from the design. Each must hit the intended CAE test or lifecycle state; `false_pass_count=0` is mandatory.

## Task 5 — Effectiveness vector + evidence trace

Implement eight reproducible metrics with numerator/denominator/value/source refs. Add requirement-to-proof/test/evidence trace output and reject tampered metric values.

## Task 6 — Independent Node verifier

Independently verify evidence hashes, overall decision, level predecessor rules, drift/lifecycle and effectiveness metrics. It must not import/invoke Python.

## Task 7 — Standard outputs and common Evidence Bundle

Emit seven outputs and compatibly extend repository-wide `machine-readable/v1/evidence.schema.json` to admit `CAE-Tnnn`. Keep `certification_claim=false` and explicit signature state.

## Task 8 — Full CI freeze gate

CI must run:

- Python/Node contract suites;
- all four Goldens at 20/20;
- negative/lifecycle registry with zero false PASS;
- P0-02/P0-06 regression workflows if common evidence vocabulary changes;
- self-contained evidence artifact staging with SHA256 index.

## Task 9 — Recovery, review, merge, main verification, Drive

- recover PR artifact;
- independently verify provider SHA256, ZIP CRC and internal file index;
- scan for private URLs/secrets/real identifiers;
- code-review full diff;
- write machine-readable frozen status;
- merge with expected head SHA;
- verify fresh main CI;
- recover main artifact and independently verify it;
- archive to project Drive, fetch it back, revalidate bytes/hash;
- update persistent project checkpoint to the post-R14 next stage.
