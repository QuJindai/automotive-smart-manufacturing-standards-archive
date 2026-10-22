# P-CAE V1 — Conformity Assessment & Implementation Effectiveness

P-CAE V1 is the R14 P0-08 executable prototype for **汽车智能制造 标准实施效果与符合性评价方法**.

Its first profile, **P-CAE-AUTO-R14 1.0**, provides one reusable C0-C3 assessment framework over frozen upstream standard evidence. It does not duplicate the P0-02 AAS or P0-06 P-ME test engines.

## Assessment chain

`Requirement -> Proof -> Test -> Evidence -> Assessment`

Every criterion binds Requirement ID, Proof Type, Test ID, Automation Flag, applicability, decision rule and evidence requirements.

Required FAIL cannot be offset by a score or exception. BLOCKED is not PASS. NOT_APPLICABLE must be permitted and justified.

## Levels

- C0 supplier declaration — `SUPPLIER_DECLARANT`
- C1 laboratory conformance — `LAB_EVALUATOR`
- C2 FAT/SAT project conformance — `FAT_SAT_EVALUATOR`
- C3 continuous production conformance — `OPERATIONS_MONITOR`

Higher levels inherit valid lower-level assessments. They do not have to duplicate all lower-level raw proof files.

## Twenty required tests

`CAE-T001..CAE-T020` cover assessment identity, CAC binding, proof integrity, automation, assessor role, N/A and exception semantics, C0-C3 prerequisites, upstream baseline binding, drift/reevaluation, validity, deterministic overall decision, effectiveness-metric recomputation, full evidence trace and truthful conformity statements.

## Four Golden packages

- `examples/c0-supplier`
- `examples/c1-lab`
- `examples/c2-fat-sat`
- `examples/c3-continuous`

All are synthetic/reference fixtures.

## Reference evaluation

```bash
python run_reference.py --package examples/c0-supplier --out ./out/c0
python run_reference.py --package examples/c1-lab --out ./out/c1
python run_reference.py --package examples/c2-fat-sat --out ./out/c2
python run_reference.py --package examples/c3-continuous --out ./out/c3
```

A Golden package prints `CAE_REQUIRED_FAILURES=0`, `CAE_PASS=20`, `CAE_OVERALL_DECISION=PASS` and `CAE_LIFECYCLE_STATE=VALID`.

## Negative and lifecycle registry

```bash
python run_negative_cases.py --out ./out/negative-summary.json
```

The registry contains 18 cases including missing/tampered proof, invalid role, illegal N/A, exception masking, broken C0/C1/C2 prerequisites, missing P0-06 proof, insufficient C3 coverage, truthful/undeclared material drift, expiry, revoked predecessor, upstream baseline mismatch, effectiveness metric tamper and fake certification claim.

A valid Test Kit run reports `CAE_NEGATIVE_CASES=18` and `CAE_NEGATIVE_FALSE_PASSES=0`.

## Independent verification

The dependency-free Node verifier does not invoke or import Python:

```bash
node independent-verifier/verify.mjs examples/c3-continuous
```

It independently recalculates evidence hashes, metrics, level prerequisites, baseline binding, drift/lifecycle, overall decision and trace/statement semantics.

## Outputs

Every evaluation emits:

- `assessment-summary.json`
- `criteria-results.json`
- `effectiveness-metrics.json`
- `evidence-trace.json`
- `reevaluation-state.json`
- `conformity-statement.json`
- `validator-evidence.json`

`validator-evidence.json` reuses the repository-wide `machine-readable/v1/evidence.schema.json` vocabulary and the `CAE-Tnnn` namespace.

## Effectiveness metrics

P-CAE emits a vector, not a weighted score:

- machine-readable coverage
- requirement testability
- automation rate
- evidence completeness
- applicable required pass rate
- cross-implementation reproducibility
- regression stability
- C3 drift closure rate

Each metric includes numerator, denominator, status and value. A denominator of zero is NOT_APPLICABLE rather than silently converted to zero.

## Lifecycle semantics

A truthfully detected material drift may leave the assessment test result itself PASS while moving lifecycle state to `REEVALUATION_REQUIRED`. Undeclared drift is a conformance failure. Expired/revoked/superseded assessments are not reusable as valid predecessors.

## Boundary

P-CAE V1 is an evaluation method/orchestrator, not a certification scheme. `certification_claim=false` is mandatory. The prototype does not implement an accredited CAB, external PKI, licensing or membership governance.
