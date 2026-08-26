# P-AAS Reference Executor V1

This is a dependency-free executable reference for the **P-AAS automotive manufacturing equipment open-data and digital engineering delivery Profile**.

It uses synthetic data only and runs AAS-T001 through AAS-T019 against an embedded localhost reference service plus a generated AASX package. It is not a claim of complete IDTA certification.

## Run

Linux/macOS/Windows PowerShell use the same Python commands from repository root:

```bash
python -m unittest discover -s reference-implementation/p-aas-v1/tests -v
python reference-implementation/p-aas-v1/run_reference.py --out ./out/p-aas-reference
```

Expected summary:

```text
AAS_PASS=19 AAS_FAIL=0 AAS_BLOCKED=0
```

Outputs:

```text
out/p-aas-reference/evidence-bundle.json
out/p-aas-reference/test-summary.json
out/p-aas-reference/sample.aasx
out/p-aas-reference/artifacts/structural-checks.json
out/p-aas-reference/artifacts/api-trace.json
```

## External target mode

```bash
python reference-implementation/p-aas-v1/run_reference.py \
  --base-url http://127.0.0.1:8081 \
  --out ./out/external-aas
```

External mode keeps local structure/semantic/AASX checks and directs HTTP probes to the supplied target. V1 deliberately marks AAS-T017 `BLOCKED` in external mode because production signature verification requires target-specific key/algorithm configuration. It does not invent a verification key.

## Synthetic security fixtures

The embedded reference service uses fixed synthetic tokens and an HS256 synthetic secret only to demonstrate repeatable conformance mechanics. Production deployments must choose authorization architecture, key management and asymmetric/signature algorithms appropriate to their security requirements.

## Scope

The reference model covers:

`equipment -> station -> program -> parameters -> status -> alarms -> software version -> documentation`

All IDs use `urn:example:automotive:*`. No real VIN, factory identifier, credential or private Drive URL belongs in this directory.
