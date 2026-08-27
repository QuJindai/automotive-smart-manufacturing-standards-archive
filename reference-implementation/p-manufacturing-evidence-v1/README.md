# P-ME V1 — Manufacturing Evidence Chain Executable Prototype

P-ME V1 is the R14 P0-06 executable slice for **key manufacturing process quality data and manufacturing evidence chains**.

The core model is process-neutral. This first implementation supplies one Automotive Profile, **P-ME-EOL 1.0**, and deliberately leaves tightening, welding, vision and calibration as future Profiles over the same core.

## What is executable

The prototype contains the six R13 product pieces:

1. normative design: `docs/superpowers/specs/2026-08-27-p0-06-manufacturing-evidence-chain-design.md`;
2. machine-readable model: `machine-readable/p0-06/manufacturing-evidence-v1.schema.json`;
3. Automotive Profile: `machine-readable/p0-06/eol-profile-v1.json`;
4. CAC: `machine-readable/p0-06/conformance-criteria-v1.json` with `ME-T001..ME-T018`;
5. automated Test Kit: Python tests, 14 registered negative/tamper cases and an independent Node.js verifier;
6. standardized Evidence Package outputs from `run_reference.py`.

All example product, station, source-record and operation identities are synthetic/reference identities. No production VIN or employee identity is required.

## Golden packages

Two executable packages are versioned:

- `examples/eol-single-pass`: `PASS -> RELEASED`;
- `examples/eol-rework-retest`: `FAIL -> REWORK -> RETEST -> PASS -> RELEASED`.

Both use the frozen P0-02 synthetic equipment identity `urn:example:automotive:asset:eol-station-001`, program `EOL_REFERENCE@1.0.0`, and the P-ME-EOL 1.0 parameter-set binding.

## Reference validation

```bash
python run_reference.py --package examples/eol-single-pass --out ./out/single
python run_reference.py --package examples/eol-rework-retest --out ./out/rework
```

A conforming Golden package prints:

```text
ME_REQUIRED_FAILURES=0
ME_PASS=18
ME_FAIL=0
ME_BLOCKED=0
```

The six generated files are:

- `validation-summary.json`
- `conformance-results.json`
- `trace-graph.json`
- `trace-query-release.json`
- `evidence-package-manifest.json`
- `validator-evidence.json`

`validator-evidence.json` uses the repository-wide `machine-readable/v1/evidence.schema.json` vocabulary and always carries `certification_claim=false`.

## Independent verification

The Node.js verifier does not invoke/import Python and uses only Node standard-library modules:

```bash
node independent-verifier/verify.mjs examples/eol-rework-retest
```

It independently verifies canonical record hashes, raw-artifact hashes, lineage transitions, attempt continuity and release legality.

## Negative / tamper registry

```bash
python run_negative_cases.py --out ./out/negative-summary.json
```

The registry covers duplicate IDs, missing provenance, object-link mismatch, program/parameter mismatch, timestamp inversion, missing/tampered raw artifacts, record tamper, unresolved parents, broken previous hash, attempt gaps, illegal retest and illegal release.

A valid Test Kit run must report `ME_NEGATIVE_FALSE_PASSES=0`.

## Integrity boundary

P-ME V1 uses SHA-256 for deterministic integrity and tamper detection. This prototype **does not** claim legal non-repudiation, electronic signature, blockchain anchoring or complete certification. A future security/signature Profile can bind signatures to these deterministic hashes without changing the evidence graph model.

## CI freeze gate

`.github/workflows/validate-p0-06-manufacturing-evidence.yml` requires:

- all Python/Node contracts green;
- both Golden chains at 18/18;
- 14 negative cases with zero false PASS;
- standardized Evidence Package/privacy checks;
- frozen P0-02 V1 19/19 regression;
- real Eclipse BaSyx regression;
- real Fraunhofer IOSB FA³ST 1.3.0 regression;
- one-day P0-06 evidence artifact for independent recovery/hash verification.
