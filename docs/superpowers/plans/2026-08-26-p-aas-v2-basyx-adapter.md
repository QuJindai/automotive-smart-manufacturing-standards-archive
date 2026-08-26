# P-AAS V2 BaSyx Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the merged P-AAS V1 executor with an implementation-neutral external adapter and prove real interoperability against pinned Eclipse BaSyx AAS Environment `2.0.0-milestone-13` on Public GitHub Actions.

**Architecture:** Preserve V1 embedded execution unchanged. Add a separate V2 package that normalizes external capability discovery, BaSyx-specific endpoint/import behavior, external P-AAS assessment, capability matrix generation, and Evidence Bundle output. Public CI starts a pinned BaSyx container, imports the synthetic automotive fixture, runs external tests, and uploads one-day evidence.

**Tech Stack:** Python 3.11+ standard library, Docker/Compose only in Public GitHub Actions, Eclipse BaSyx AAS Environment milestone-13.

**Spec:** `docs/superpowers/specs/2026-08-26-p-aas-v2-basyx-adapter-design.md`

## Global Constraints
- V1 deterministic baseline must remain unchanged and green.
- Core external runner must not import BaSyx Java classes or depend on a BaSyx SDK.
- Pin `eclipsebasyx/aas-environment:2.0.0-milestone-13`; never use moving SNAPSHOT in acceptance CI.
- No standards PDFs, real credentials, private Drive IDs/URLs, VINs, employee data, or proprietary factory data.
- Unsupported optional/security capability must never be reported as PASS.
- Evidence Bundle result vocabulary remains V1-compatible; capability status is a separate field/matrix.

---

### Task 1: External adapter model and capability semantics

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/__init__.py`
- Create: `reference-implementation/p-aas-v2/paas_v2/external.py`
- Create: `reference-implementation/p-aas-v2/paas_v2/capabilities.py`
- Test: `reference-implementation/p-aas-v2/tests/test_external.py`

**Interfaces:**
- `CapabilityStatus`: `SUPPORTED_VERIFIED`, `SUPPORTED_NOT_VERIFIED`, `UNSUPPORTED_WITH_EVIDENCE`, `UNKNOWN`, `BLOCKED`.
- `CapabilityEvidence` dataclass.
- `CapabilityRecord` dataclass.
- `ExternalAASAdapter` protocol/base class with health, discover, import, read, query, security/signing probes, and OpenAPI methods.

- [ ] Write failing tests for enum values, JSON serialization, and adapter contract.
- [ ] Run tests and verify import/attribute failures.
- [ ] Implement minimal dataclasses/helpers.
- [ ] Run tests to green.

### Task 2: Identifier encoding and generic HTTP evidence transport

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/http.py`
- Test: `reference-implementation/p-aas-v2/tests/test_http.py`

**Interfaces:**
- `encode_identifier(value: str) -> str` using URL-safe base64 without padding for DotAAS path identifiers.
- `request(method, url, body=None, headers=None, timeout=10) -> HttpEvidence`.

- [ ] Write red tests for deterministic encoding and bounded HTTP evidence/body capture.
- [ ] Implement standard-library `urllib` transport.
- [ ] Verify transport errors remain typed `TransportBlocked` rather than fake FAIL.

### Task 3: BaSyx adapter against a fake HTTP service

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/basyx.py`
- Test: `reference-implementation/p-aas-v2/tests/test_basyx_adapter.py`

**Interfaces:**
- `BasyxAdapter(base_url, target_metadata)`.
- `fetch_openapi()`, `health()`, `discover_capabilities()`, `import_environment()`, `read_aas()`, `read_submodel()`.

- [ ] Write a local fake server test exposing `/v3/api-docs`, `/upload`, `/shells/{encoded}`, `/submodels/{encoded}`.
- [ ] Verify adapter reads OpenAPI paths and classifies core capabilities.
- [ ] Verify JSON import route is recorded in evidence.
- [ ] Verify identifiers are encoded centrally.
- [ ] Implement minimal BaSyx adapter until tests pass.

### Task 4: External assessment result mapping

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/assessment.py`
- Test: `reference-implementation/p-aas-v2/tests/test_assessment.py`

**Interfaces:**
- `AssessmentResult(test_id, result, capability_status, reason, assertions, artifacts)`.
- `classify_optional(capability_record) -> tuple[result, capability_status]`.

- [ ] Test required core mismatch => FAIL.
- [ ] Test missing authorization on unsecured target => NOT_APPLICABLE + UNSUPPORTED_WITH_EVIDENCE.
- [ ] Test transport/OpenAPI uncertainty => BLOCKED.
- [ ] Implement minimal classification rules.

### Task 5: Reuse V1 structural/semantic checks on external objects

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/v1_bridge.py`
- Test: `reference-implementation/p-aas-v2/tests/test_v1_bridge.py`

**Interfaces:**
- Read returned AAS/Submodels/ConceptDescriptions into a `SampleBundle`-compatible normalized environment.
- Invoke V1 `rules.py` and `semantic.py` checks without copying their logic.

- [ ] Write red test using V1 synthetic object responses.
- [ ] Add import-path bridge to V1 modules.
- [ ] Map T002..T008 results to external assessment records.
- [ ] Verify a mutated returned semantic field produces FAIL.

### Task 6: Capability matrix and evidence outputs

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/output.py`
- Test: `reference-implementation/p-aas-v2/tests/test_output.py`

**Interfaces:**
- Write `implementation-capability-matrix.json` and `.csv`.
- Write `interop-summary.json` with `certification_claim=false`.
- Build V1-schema-compatible `evidence-bundle.json`.

- [ ] Write red tests for deterministic columns/keys, truthful unsupported status, SHA-256 artifacts, and absence of Drive URLs.
- [ ] Implement writers and hashing.
- [ ] Validate 19 unique AAS IDs can coexist with N/A/unsupported outcomes.

### Task 7: External runner and CLI

**Files:**
- Create: `reference-implementation/p-aas-v2/paas_v2/runner.py`
- Create: `reference-implementation/p-aas-v2/run_external.py`
- Test: `reference-implementation/p-aas-v2/tests/test_runner.py`

**Interfaces:**
- `run_external(adapter, fixture, out_dir) -> dict`.
- CLI: `python reference-implementation/p-aas-v2/run_external.py --adapter basyx --base-url URL --fixture PATH --out PATH --target-version VALUE`.

- [ ] Write end-to-end red test using fake BaSyx service.
- [ ] Implement discovery/import/read/core assessment/optional classification/output orchestration.
- [ ] Assert no required core FAIL/BLOCKED => exit 0; required core failure/block => non-zero.

### Task 8: BaSyx milestone-13 fixture and Public CI

**Files:**
- Create: `reference-implementation/p-aas-v2/basyx/application.properties`
- Create: `reference-implementation/p-aas-v2/basyx/docker-compose.yml`
- Create: `reference-implementation/p-aas-v2/basyx/fixture/environment.json`
- Create: `.github/workflows/validate-p-aas-basyx.yml`
- Create: `reference-implementation/p-aas-v2/README.md`

- [ ] Add CI first so the BaSyx job is red until the adapter/fixture can interoperate.
- [ ] Pin `eclipsebasyx/aas-environment:2.0.0-milestone-13`.
- [ ] Start container, poll `http://127.0.0.1:8081/v3/api-docs`, dump logs on failure.
- [ ] Run V1 regression job independently.
- [ ] Run V2 external CLI and verify generated capability/evidence files.
- [ ] Upload one-day V2 evidence artifact.
- [ ] `docker compose down -v` in an `always()` cleanup step.

### Task 9: Truthful BaSyx acceptance tuning

**Files:**
- Modify only adapter/path/fixture files proven by the first real CI evidence.
- Add regression tests for every BaSyx-specific mismatch found.

- [ ] Inspect first real container logs/OpenAPI/output.
- [ ] For each mismatch, identify whether it is adapter encoding/path/fixture defect or real unsupported capability.
- [ ] Write a failing regression test before changing adapter behavior.
- [ ] Fix only the identified root cause.
- [ ] Re-run full Public CI until core interoperability passes and optional/security gaps are truthfully classified.

### Task 10: Final verification and archive metadata

**Files:**
- Modify: `machine-readable/v1/README.md`
- Create: `archive/p-aas-v2-basyx-status.json`

- [ ] Verify V1 Public CI still green.
- [ ] Verify V2 local/fake tests green.
- [ ] Verify BaSyx milestone-13 Public CI green.
- [ ] Verify outputs contain `certification_claim=false` and no private data.
- [ ] Record pinned image, CI run, capability counts, core result counts and artifact digest in metadata-only archive status.