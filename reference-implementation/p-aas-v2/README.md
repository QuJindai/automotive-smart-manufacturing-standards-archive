# P-AAS V2 — External AAS Cross-Implementation Baseline

V2 keeps the V1 embedded reference server as the deterministic baseline and adds implementation-neutral external adapters. R14 P0-02 cross-validates the same automotive fixture and the same `AAS-T001..AAS-T019` Profile against two independent real AAS implementations:

- Eclipse BaSyx AAS Environment pinned to `2.0.0-milestone-13`.
- Fraunhofer IOSB FA³ST Service pinned to `1.3.0`.

The objective is interoperability evidence, not vendor-specific green status. Unsupported capabilities remain explicit and must not be promoted to PASS without runtime evidence.

## Local adapter tests

```bash
cd reference-implementation/p-aas-v2
PYTHONPATH=.:tests:../p-aas-v1 python -m unittest discover -s tests -v
```

## Eclipse BaSyx target

```bash
python reference-implementation/p-aas-v2/run_external.py \
  --adapter basyx \
  --base-url http://127.0.0.1:8081 \
  --fixture reference-implementation/p-aas-v2/basyx/fixture/environment.json \
  --target-version 2.0.0-milestone-13 \
  --out ./out/p-aas-v2-basyx
```

The BaSyx adapter reads `/v3/api-docs`, attempts `/upload`, and transparently falls back to AAS/Submodel/ConceptDescription repository POSTs when required.

## Fraunhofer IOSB FA³ST target

The public acceptance workflow starts the pinned image `fraunhoferiosb/faaast-service:1.3.0` with local-test SSL disabled, exercises the `/api/v3.0` repository API, imports the same fixture through `/api/v3.0/import`, reads the imported AAS/Submodels/ConceptDescriptions, and verifies AASX serialization.

```bash
python reference-implementation/p-aas-v2/run_external.py \
  --adapter faaast \
  --base-url http://127.0.0.1:8082 \
  --fixture reference-implementation/p-aas-v2/basyx/fixture/environment.json \
  --target-version 1.3.0 \
  --out ./out/p-aas-v2-faaast
```

FA³ST 1.3.0 security mechanisms are not part of the exercised target capability set, so authorization/signing tests remain `NOT_APPLICABLE` with `UNSUPPORTED_WITH_EVIDENCE`; they are never reported as automatic PASS.

## Evidence outputs

Each external run writes:

- `implementation-capability-matrix.json`
- `implementation-capability-matrix.csv`
- `interop-summary.json`
- `evidence-bundle.json`
- `openapi.json` or endpoint-probe payload at the same compatibility path
- `import-response.json`
- `returned-environment.json`
- `serialized.aasx` when package serialization succeeds

## Acceptance semantics

`PASS` is only used for executed and verified behavior. Optional/security features not implemented or not configured in the target profile are `NOT_APPLICABLE` with capability status `UNSUPPORTED_WITH_EVIDENCE`; advertised but unverified optional features become `BLOCKED`, never automatic PASS.

Required R14 P0-02 cross-validation gates are `AAS-T001..T009`, `AAS-T011`, `AAS-T012`, and `AAS-T018`. P0-02 can be frozen only when both independent real targets have zero required `FAIL`/`BLOCKED`, V1 regression remains 19/19, artifacts are recovered and their SHA-256 digests are independently revalidated.

This is an interoperability/Profile reference test. `certification_claim=false` remains mandatory and no complete IDTA certification is claimed.
