# P-AAS V2 — External AAS Adapter / Eclipse BaSyx Baseline

V2 keeps the V1 embedded reference server as the deterministic baseline and adds an implementation-neutral external adapter. The first real target is Eclipse BaSyx AAS Environment pinned to `2.0.0-milestone-13`.

## Local fake-adapter tests

```bash
cd reference-implementation/p-aas-v2
PYTHONPATH=.:tests:../p-aas-v1 python -m unittest discover -s tests -v
```

## External target

```bash
python reference-implementation/p-aas-v2/run_external.py \
  --adapter basyx \
  --base-url http://127.0.0.1:8081 \
  --fixture reference-implementation/p-aas-v2/basyx/fixture/environment.json \
  --target-version 2.0.0-milestone-13 \
  --out ./out/p-aas-v2-basyx
```

The adapter first reads `/v3/api-docs`, attempts `/upload` with JSON, and transparently falls back to AAS/Submodel/ConceptDescription repository POSTs when needed. It writes:

- `implementation-capability-matrix.json`
- `implementation-capability-matrix.csv`
- `interop-summary.json`
- `evidence-bundle.json`
- `openapi.json`
- `import-response.json`
- `returned-environment.json`

## Interpretation

`PASS` is only used for executed/verified behavior. Optional/security features not configured in the baseline are `NOT_APPLICABLE` with capability status `UNSUPPORTED_WITH_EVIDENCE`; advertised but unverified optional features become `BLOCKED`, never automatic PASS.

This is an interoperability/Profile reference test, not a claim of complete IDTA certification.
