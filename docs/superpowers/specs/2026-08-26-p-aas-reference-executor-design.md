# P-AAS Reference Executor V1 Design

## Status
Approved direction from the preceding project phase: turn the P-AAS machine-readable Profile into an executable automotive-manufacturing reference implementation and run AAS-T001 through AAS-T019 end to end.

## Goal
Build a small, reproducible reference implementation that proves the existing P-AAS rules can become executable checks, HTTP/API conformance probes, AASX package checks and C0-C2 evidence without storing copyrighted standards text in Git.

The V1 reference subject is a synthetic automotive EOL/test-station asset model covering:

`equipment -> station -> program -> parameters -> status -> alarms -> software version -> documentation`

No proprietary factory data is used.

## Non-goals
- Do not implement P-AI model/TEVV runners in this phase.
- Do not claim full IDTA AAS conformance beyond the P-AAS rules/tests implemented here.
- Do not build a production AAS server.
- Do not hard-code company-specific identifiers, thresholds or secrets.
- Do not commit standards PDFs or private Drive IDs/URLs.

## Approaches considered

### A. Pure Python standard-library reference executor — selected
A self-contained Python package uses `json`, `urllib`, `http.server`, `zipfile`, `hmac`, `hashlib` and `unittest`. It includes a minimal reference HTTP service, structural/semantic rule evaluators, an AASX builder/checker, JWS HS256 reference signing and Evidence Bundle generation.

Benefits: no PyPI dependency, deterministic Public GitHub Actions, easy Windows/Linux execution, small attack surface, easy to inspect. Cost: it is intentionally not a complete AAS SDK/server.

### B. Eclipse BaSyx or another AAS server
Closer to a production AAS stack and useful later for interoperability. Rejected for V1 because it makes the executor dependent on a server distribution, Java/container lifecycle and specific product behavior.

### C. Full Python AAS SDK integration
Would provide broader metamodel fidelity. Rejected for V1 because the goal is to prove the Profile/test/evidence chain, not to create another SDK integration layer.

## Architecture

Repository area:

```text
machine-readable/v1/
  automotive-manufacturing-profile.v1.json
  test-cases.yaml
  profile.schema.json
  evidence.schema.json

reference-implementation/p-aas-v1/
  README.md
  run_reference.py
  paas_ref/
    __init__.py
    __main__.py
    sample.py
    rules.py
    semantic.py
    policy.py
    jws.py
    aasx.py
    api.py
    mock_server.py
    evidence.py
    runner.py
  examples/automotive-eol-station/
    aas-environment.json
    capabilities.json
    semantic-dictionary.json
    supplementary/
      manual.txt
      program-version-note.txt
      certificate.txt
  tests/
    test_rules.py
    test_semantic.py
    test_policy_jws.py
    test_aasx.py
    test_api.py
    test_evidence_runner.py
```

### `sample.py`
Loads the synthetic AAS environment, capabilities and semantic/unit dictionary. It exposes identifiers used by the embedded HTTP service and test runner.

### `rules.py` + `semantic.py`
Pure functions implement P-AAS structural and semantic checks: asset kind/identifier, Submodel semantic IDs, ConceptDescription/IEC61360-like data specification presence, preferred-language coverage, unit/unitId consistency and unit resolvability.

### `policy.py`
Implements a small deterministic ABAC reference policy. Inputs are subject, resource and context attributes; output is an auditable allow/deny decision with reason codes. It demonstrates P-AAS access-rule test mechanics, not a production authorization engine.

### `jws.py`
Implements compact JWS HS256 using Python `hmac`/`hashlib`. The test proves integrity/tamper detection and evidence generation. Documentation explicitly says production deployments should select key management and asymmetric algorithms appropriate to their security architecture.

### `aasx.py`
Builds an AASX-like OPC ZIP from text fixtures, then validates `[Content_Types].xml`, `_rels/.rels`, `aasx-origin`, AAS environment relationship and supplementary-file relationships. Generated `.aasx` is a CI/output artifact, not stored as a binary source fixture.

### `mock_server.py`
A `ThreadingHTTPServer` exposes only the operations needed to exercise AAS-T010 through AAS-T017:
- query endpoint with valid/invalid requests;
- read AAS by ID;
- read Submodel by ID;
- protected-resource 401/403 behavior;
- create/update privilege checks;
- ABAC authorization endpoint;
- `/$signed` JWS response.

The reference server uses synthetic fixed test tokens only inside the fixture environment. Real deployments use `--base-url` and caller-provided tokens/URLs.

### `api.py`
HTTP client/probe functions. The same probes can target the embedded reference service or a real AAS service configured by environment/CLI arguments.

### `evidence.py`
Builds one Evidence Bundle conforming to the structure of `machine-readable/v1/evidence.schema.json`. Every test result carries test ID, level, result, linked Profile rules, assertions and SHA-256-addressed evidence artifacts.

### `runner.py`
Orchestrates AAS-T001..T019. Default mode starts the embedded reference service on an ephemeral localhost port, runs all tests, builds/validates AASX, then writes:

```text
out/evidence-bundle.json
out/test-summary.json
out/sample.aasx
out/artifacts/*
```

Exit code is non-zero if any required test is `FAIL` or `BLOCKED`.

## Synthetic automotive object model

The sample AAS environment includes:
- Asset: `urn:example:automotive:asset:eol-station-001`
- AAS: EOL test station instance
- Status Submodel
- Software Version Submodel
- Process Parameters Submodel
- Alarm Submodel
- Documentation Submodel
- ConceptDescriptions for state, version, parameter and units

The values are synthetic examples, not assertions about any real factory.

## AAS-T001..T019 coverage

- T001: every P-AAS rule has source traceability, machine check and a known TestID.
- T002: `assetKind` is Type/Instance as expected.
- T003: globalAssetId or specificAssetIds exists.
- T004: required Submodels/properties have semantic references.
- T005: key ConceptDescriptions carry IEC61360-style data specification metadata.
- T006: preferredName contains English; automotive sample also contains Chinese.
- T007: `unit` and `unitId` resolve consistently.
- T008: unit IDs resolve through the semantic/unit dictionary.
- T009: required capability interfaces are declared.
- T010: query valid/invalid behavior.
- T011: AAS read by ID.
- T012: Submodel read by ID.
- T013: unauthenticated protected access -> 401.
- T014: authenticated/no privilege -> 403 without payload disclosure.
- T015: CREATE/UPDATE privilege separation and expected status codes.
- T016: ABAC decisions change with factory/role/time/equipment-state attributes and are logged.
- T017: signed object verifies; tampered object fails.
- T018: AASX entry/relationship/content-type graph valid.
- T019: supplementary files are present and relationship-linked.

## Error handling
- Malformed fixture JSON: fail-fast before tests begin.
- Missing configured semantic IDs/languages/files: corresponding rule test fails with a structured assertion.
- HTTP transport failure: API test becomes `BLOCKED`, not an invented pass/fail.
- Unexpected HTTP status/body: test is `FAIL` with observed status and a bounded body snippet.
- AASX malformed/missing relationship: relevant test fails and the package remains available as evidence.
- Missing signing key in external mode: T017 is `BLOCKED`; embedded mode uses an ephemeral synthetic secret.

## Security and privacy
- Reference tokens/HS256 secret are synthetic and generated for local test use only.
- No real credentials, Drive IDs, VINs, employee identifiers or factory secrets are committed.
- Evidence files contain only synthetic/reference data unless a user deliberately runs against an external target.

## Verification
CI must run from repository root:

```bash
python -m unittest discover -s reference-implementation/p-aas-v1/tests -v
python reference-implementation/p-aas-v1/run_reference.py --help
python reference-implementation/p-aas-v1/run_reference.py --out /tmp/paas-evidence
```

Acceptance requires:
- unit suite green;
- AAS-T001..T019 all `PASS` against the embedded reference service;
- Evidence Bundle contains 19 unique test results;
- generated AASX is valid according to V1 checks;
- CI source tree contains no committed `.aasx`, standards PDF, secret or private Drive URL.

## Future extension points
- External BaSyx/other AAS server adapter using the same probes.
- Full IDTA conformance corpus mapping.
- Asymmetric JWS/PKI profiles.
- P-AI executor as a separate subsystem consuming the same Evidence Bundle model.
