# R14 P0-06 Manufacturing Evidence Chain — Design

## 1. Goal and frozen scope

Build the first executable prototype for **P0-06 汽车制造 关键工艺质量数据与制造证据链通用要求** without reopening R00-R13 or modifying the frozen P0-02 baseline.

The generic standard product is named **P-ME V1 (Manufacturing Evidence V1)**. Its first Automotive Profile is **EOL Detection Profile V1**. Tightening, welding, vision and calibration will extend the same core model later; they must not fork the evidence engine.

The executable slice must implement the R13 six-piece product pattern:

1. Normative Text
2. Machine-readable Manufacturing Evidence Model
3. Automotive EOL Profile
4. Conformance Units / CAC
5. Automated Test Kit
6. Standardized Evidence Package output

This prototype is an interoperability/conformance reference, not a legal electronic-signature system, a production MES replacement, or a certification claim.

## 2. Normative model

Each evidence record represents one observable manufacturing-quality assertion and MUST contain:

- `evidence_id`: globally unique within a package.
- `schema_version`, `profile_id`, `profile_version`.
- `subject`: synthetic product/vehicle identity and operation identity.
- `source`: source system, equipment, source record id and acquisition identity.
- `process_context`: process/station/equipment references.
- `measurement`: characteristic, raw value, normalized/result value, unit, judgment and explicit measurement-uncertainty declaration.
- `execution_context`: program id/version, parameter-set id/hash and tool state.
- `time`: event time and collection time in RFC3339 UTC.
- `lineage`: attempt number, relation type, parent evidence ids and previous-record hash.
- `raw_artifacts`: relative artifact references with MIME type, byte size and SHA-256.
- `disposition`: process decision (`PASS`, `FAIL`, `REWORK`, `RETEST`, `RELEASED`) plus rule id.
- `integrity`: canonical-record SHA-256.

No real VIN, employee identity, private Drive URL, access token or other secret may appear in fixtures or evidence packages.

## 3. Trace Graph

The validator MUST derive a deterministic graph from records. Required edge types:

- `SUBJECT_OF`
- `GENERATED_BY`
- `USES_PROGRAM`
- `USES_PARAMETER_SET`
- `HAS_RAW_ARTIFACT`
- `DERIVED_FROM`
- `RETEST_OF`
- `REPAIR_OF`
- `RELEASES`

The graph must permit deterministic queries from final release evidence back to source record, program/version, parameter set, equipment and raw artifact. Artifact traceability MUST be represented by `HAS_RAW_ARTIFACT`; it must not rely on a non-graph side channel.

## 4. EOL Detection Profile V1

The profile reuses the frozen P0-02 synthetic EOL station identity `urn:example:automotive:asset:eol-station-001` and program `EOL_REFERENCE` / `1.0.0`.

EOL Profile requirements:

- equipment identity is fixed to or explicitly mapped from the P0-02 fixture;
- program id/version and parameter-set hash are mandatory;
- quantitative measurements require either a numeric uncertainty object or an explicit `not_applicable_reason`;
- a release may only follow a PASS result for the same subject/operation lineage;
- FAIL -> REWORK/REPAIR -> RETEST -> PASS -> RELEASED is a valid chain;
- attempt numbers are monotonic and contiguous per subject/operation;
- event time must not move backwards in a lineage; collection time must not precede event time;
- raw evidence must remain addressable by relative package URI and exact SHA-256.

## 5. Conformance Units / CAC

P-ME V1 defines 18 executable tests:

- `ME-T001` package/schema identity present.
- `ME-T002` evidence ids unique.
- `ME-T003` source provenance complete.
- `ME-T004` subject/process/equipment linkage complete.
- `ME-T005` program and parameter-set version binding complete.
- `ME-T006` RFC3339 UTC timestamps parse and order correctly.
- `ME-T007` measurement raw/result/unit/judgment complete.
- `ME-T008` uncertainty explicitly declared.
- `ME-T009` raw artifact exists, size matches and SHA-256 matches.
- `ME-T010` canonical record hash matches content.
- `ME-T011` parent evidence references resolve.
- `ME-T012` previous-record hash matches parent/previous record.
- `ME-T013` attempt numbers are contiguous and monotonic.
- `ME-T014` retest/rework relation semantics are legal.
- `ME-T015` release has a valid PASS predecessor for the same subject/operation.
- `ME-T016` trace graph is complete for mandatory provenance edges, including raw artifacts.
- `ME-T017` trace query from release to source/program/parameter/artifact succeeds.
- `ME-T018` package round-trip is deterministic and long-term readable using only JSON + raw artifacts.

All 18 tests are required for the EOL V1 prototype. A required violation is `FAIL`. `BLOCKED` is used only when the test cannot execute because a required package component is unavailable/unreadable; it must never be converted to PASS.

## 6. Automated Test Kit

The repository will contain:

- Python reference producer/validator/trace engine using the standard library only;
- an independent Node.js verifier with no third-party packages;
- a valid single-pass EOL package;
- a valid FAIL -> REWORK -> RETEST -> PASS -> RELEASED package;
- negative fixtures for missing provenance, broken object linkage, timestamp inversion, program/parameter mismatch, missing/tampered raw artifact, record-hash tamper, broken parent hash, duplicate id, attempt gap and illegal release.

The Node verifier must independently implement the core canonicalization/hash and lineage rules; it must not call or import the Python validator.

## 7. Evidence Package output

Every executed validation writes:

- `validation-summary.json`
- `conformance-results.json`
- `trace-graph.json`
- `trace-query-release.json`
- `evidence-package-manifest.json`
- `validator-evidence.json`

`validator-evidence.json` records profile/schema/test-kit versions, test results, input package hash, generated outputs and their SHA-256 values. It MUST set `certification_claim=false` and MUST use the repository-wide `machine-readable/v1/evidence.schema.json` bundle vocabulary rather than inventing a parallel conformance-evidence format. The generic evidence schema may be extended only compatibly to admit the `ME-Tnnn` test-id namespace.

## 8. Acceptance gate

P0-06 may be frozen only when all are true on the same mainline commit:

1. Python unit/integration suite is green.
2. Python reference validator returns `ME_REQUIRED_FAILURES=0` and all 18 tests PASS for both valid Golden packages.
3. Every negative fixture fails the intended test and does not create false PASS.
4. Independent Node verifier agrees with Python on both valid packages and the selected tamper/lineage negative cases.
5. Existing P0-02 BaSyx/FA3ST and V1 19/19 regression remain green.
6. CI artifacts are recovered, ZIP integrity checked and SHA-256 independently revalidated.
7. Evidence artifacts contain no private Drive URLs or real identifiers.
8. Final evidence is archived to the project Drive and read back for independent byte/hash verification.

## 9. Non-goals

- No database, blockchain, distributed ledger or external PKI.
- No claim that SHA-256 provides legal non-repudiation.
- No production retention-period policy in this prototype.
- No implementation of tightening/welding/vision/calibration profiles in this slice.
- No replacement or rewrite of the frozen P0-02 AAS adapter stack.
