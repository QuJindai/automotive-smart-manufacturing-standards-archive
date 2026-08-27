# P-AAS V2 External AAS Adapter + BaSyx Interoperability Design

## Status
Approved 2026-08-26. This extends the merged P-AAS V1 reference executor without weakening its deterministic embedded baseline.

## Goal
Add an implementation-neutral external AAS adapter and use Eclipse BaSyx AAS Environment as the first real implementation under test. Produce a capability matrix and conformity evidence that clearly distinguishes `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE`, and `UNSUPPORTED_WITH_EVIDENCE`.

## Official BaSyx baseline
The implementation target is the Eclipse BaSyx Java V2 AAS Environment. Official project documentation states that the AAS Environment aggregates AAS Repository, Submodel Repository, and ConceptDescription Repository; exposes aggregated OpenAPI at `/v3/api-docs`; supports preconfiguration of JSON/XML/AASX environments; and exposes `/upload` for serialized environment upload.

For reproducibility V2 pins:

```text
eclipsebasyx/aas-environment:2.0.0-milestone-13
```

rather than the moving `2.0.0-SNAPSHOT` tag. The milestone-13 image was available on the official `eclipsebasyx/aas-environment` DockerHub repository at the design baseline date.

The baseline test configuration uses the official component defaults:

```properties
server.port=8081
spring.application.name=AAS Environment
basyx.backend=InMemory
```

Security/authorization is not enabled in the first BaSyx baseline container. Therefore security-specific P-AAS tests are capability-classified rather than falsely passed.

## Architecture

```text
P-AAS V1 rules/tests
       |
       +-- embedded adapter -> V1 reference server -> deterministic 19/19 regression
       |
       +-- external adapter interface
               |
               +-- BaSyx adapter -> BaSyx AAS Environment milestone-13
               +-- future adapters -> other AAS implementations

external adapter
  -> capability discovery
  -> fixture import/bootstrap
  -> mapped Profile tests
  -> raw HTTP/schema evidence
  -> implementation-capability-matrix.json/csv
  -> interop-summary.json
  -> evidence-bundle.json
```

## Boundaries
- Do not make the core runner depend on BaSyx classes or Java.
- Do not claim full IDTA certification.
- Do not treat unsupported optional/vendor-specific capability as PASS.
- Do not treat an intentionally unsecured baseline as a security failure; classify security tests as `UNSUPPORTED_WITH_EVIDENCE` unless a secured target is explicitly configured.
- No standards PDFs, real credentials, private Drive IDs, factory data, VINs, or employee data.
- Public CI uses a public repository and standard GitHub-hosted Ubuntu runner.

## Components

### `external.py`
Defines `ExternalAASAdapter`, `Capability`, `CapabilityStatus`, `ProbeEvidence`, and a normalized adapter result model. The executor consumes this interface only.

Required adapter operations:
- `health()`
- `discover_capabilities()`
- `import_environment()`
- `read_aas()`
- `read_submodel()`
- `query()` when advertised
- `probe_unauthorized()` / `probe_forbidden()` when authorization is configured
- `probe_create_update_privileges()` when authorization is configured
- `probe_signed()` when a signing endpoint/profile exists
- `fetch_openapi()`

### `basyx.py`
BaSyx-specific path/serialization adapter. It may know `/upload`, `/v3/api-docs`, `/shells`, `/submodels`, and BaSyx response envelopes; no other module may contain BaSyx-specific branching.

### `capabilities.py`
Produces a normalized capability matrix with fields:

```text
capability_id
profile_test_ids
advertised
verified
status
source
observed_endpoint
http_status
reason
artifact_refs
```

Statuses:
- `SUPPORTED_VERIFIED`
- `SUPPORTED_NOT_VERIFIED`
- `UNSUPPORTED_WITH_EVIDENCE`
- `UNKNOWN`
- `BLOCKED`

### `external_runner.py`
Runs the subset of P-AAS tests meaningful for an external implementation. It reuses V1 structural/semantic checks on returned AAS/Submodel objects and reuses the V1 evidence model.

It must not mutate V1 embedded behavior.

### BaSyx CI fixture

```text
reference-implementation/p-aas-v2/
  basyx/
    application.properties
    docker-compose.yml
    fixture/
      environment.json
```

CI starts one pinned AAS Environment container with in-memory backend, waits for `/v3/api-docs`, imports the synthetic automotive environment, executes the adapter, then always destroys the container.

## Test classification

### Core external interoperability
Expected to be executable against the unsecured BaSyx baseline:
- AAS-T002 asset kind
- AAS-T003 asset identifier
- AAS-T004 semantic references
- AAS-T005 IEC61360-style semantic metadata
- AAS-T006 multilingual preferredName
- AAS-T007 unit/unitId consistency
- AAS-T008 unit resolvability
- AAS-T009 capability/interface declaration/probe
- AAS-T011 read AAS by ID
- AAS-T012 read Submodel by ID
- AAS-T018 package/serialization evidence when supported by adapter path
- AAS-T019 supplementary file linkage when a package artifact is available

### Capability-dependent
- AAS-T010 query: execute only if a supported query/search capability is advertised/probed.
- AAS-T013/T014/T015/T016: authorization/RBAC/ABAC-dependent; unsecured baseline => `UNSUPPORTED_WITH_EVIDENCE`.
- AAS-T017: signing-dependent; absent standard/implementation endpoint => `UNSUPPORTED_WITH_EVIDENCE`.

### V1-only reference mechanic
AAS-T001 remains a Profile asset integrity check and runs against repository-local machine assets, not the external server.

## Result semantics
Every test-like external assessment has both:

```json
{
  "test_id": "AAS-T013",
  "result": "NOT_APPLICABLE",
  "capability_status": "UNSUPPORTED_WITH_EVIDENCE",
  "reason": "authorization_disabled_in_target_profile",
  "evidence": [{"kind":"openapi_or_probe", "...":"..."}]
}
```

`UNSUPPORTED_WITH_EVIDENCE` is a capability classification. Evidence Bundle `result` remains compatible with V1 schema by using `NOT_APPLICABLE` or `BLOCKED` as appropriate.

## BaSyx import strategy
Preferred order:
1. `POST /upload` with JSON fixture and `Accept: application/json` if accepted by milestone-13.
2. If JSON upload semantics differ, use the repository APIs discovered from `/v3/api-docs` to create AAS, Submodels, and ConceptDescriptions.

The adapter records which import route succeeded. It must not hide fallback behavior.

## API identifier encoding
BaSyx follows DotAAS REST identifier encoding expectations. The adapter provides one canonical `encode_identifier()` function and tests it independently. No caller may concatenate raw global IDs into URL paths.

## Capability discovery
Discovery combines:
1. OpenAPI inspection from `/v3/api-docs`;
2. bounded HTTP probes for candidate endpoints;
3. explicit target configuration for security credentials/features.

OpenAPI absence => `BLOCKED`, not unsupported.
Endpoint absent from a healthy OpenAPI document plus confirmed 404 probe => `UNSUPPORTED_WITH_EVIDENCE`.

## Evidence outputs
V2 writes:

```text
out/
  evidence-bundle.json
  interop-summary.json
  implementation-capability-matrix.json
  implementation-capability-matrix.csv
  openapi.json
  artifacts/
    import-response.*
    http-traces.jsonl
    returned-aas.json
    returned-submodels.json
```

`interop-summary.json` contains target implementation, image/tag, start/end time, capability counts, PASS/FAIL/BLOCKED/N/A counts, and a `certification_claim=false` field.

## CI
New workflow: `.github/workflows/validate-p-aas-basyx.yml`.

Jobs:
1. `v1-regression`: existing Python tests + embedded 19/19 baseline.
2. `basyx-milestone-13`: Docker pull/start, health/OpenAPI gate, fixture import, V2 external run, output verification, upload 1-day evidence artifact, cleanup in `always()`.

The workflow never uses the moving SNAPSHOT tag.

## Failure policy
- Container cannot start/pull: job fails, external run `BLOCKED` evidence if output could be produced.
- `/v3/api-docs` unhealthy after timeout: job fails with container logs.
- Fixture import failure: job fails and uploads response/logs.
- Core read/semantic test mismatch: `FAIL` and job fails.
- Unsupported optional/security capability: `NOT_APPLICABLE + UNSUPPORTED_WITH_EVIDENCE`; does not fail the job.
- Unknown capability due incomplete evidence: `BLOCKED`; job fails unless explicitly waived by future Profile policy.

## Acceptance
V2 is complete when:
- V1 regression remains 26/26 unit/integration tests and embedded AAS-T001..T019 19/19 PASS.
- BaSyx milestone-13 container starts on Public Actions and reports healthy OpenAPI.
- Synthetic automotive fixture is imported.
- AAS and Submodel retrieval is verified through the external adapter.
- Structural/semantic returned-object checks pass.
- Capability-dependent items are truthfully classified with evidence.
- capability JSON and CSV are generated.
- external Evidence Bundle is schema-compatible.
- public CI is green without private secrets or standard fulltext.