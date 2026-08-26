# P-AAS Reference Executor V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free Python reference implementation that executes AAS-T001 through AAS-T019 against a synthetic automotive EOL/test-station AAS subject and emits a structured Evidence Bundle.

**Architecture:** A small Python package under `reference-implementation/p-aas-v1/` separates fixture loading, structural/semantic rules, ABAC/JWS, AASX packaging, HTTP probes, embedded mock service and evidence orchestration. The existing machine-readable Profile and Test Case assets become the source of truth for rule/test IDs; generated AASX/evidence are runtime artifacts only.

**Tech Stack:** Python 3.11+ standard library only (`json`, `unittest`, `urllib`, `http.server`, `zipfile`, `hmac`, `hashlib`, `xml.etree.ElementTree`, `threading`, `tempfile`).

**Spec:** `docs/superpowers/specs/2026-08-26-p-aas-reference-executor-design.md`

## Global Constraints

- Public repository; never commit standards PDFs, real credentials, private Drive IDs/URLs, real VINs or factory secrets.
- Use synthetic automotive identifiers and values only.
- Do not implement P-AI execution in this phase.
- AAS-T001 through AAS-T019 must each produce one unique result in the final Evidence Bundle.
- No PyPI dependency is permitted for the V1 executor.
- JWS test uses synthetic HS256 only and documentation must state that production key/algorithm selection is out of scope.
- Generated `.aasx` and evidence output are CI/runtime artifacts, not source fixtures.

---

### Task 1: Make P-AAS machine assets self-contained in Git

**Files:**
- Create: `machine-readable/v1/automotive-manufacturing-profile.v1.json`
- Create: `machine-readable/v1/test-cases.yaml`
- Modify: `.github/workflows/validate-machine-assets.yml`

**Interfaces:**
- Consumes: existing `profile.schema.json`, `evidence.schema.json`, current V1 Profile/Test assets.
- Produces: repository-local Profile rules and test IDs usable by executor/CI.

- [ ] **Step 1: Add a failing CI invariant**

Extend the workflow Python block before files exist:

```python
profile = json.loads((root/'automotive-manufacturing-profile.v1.json').read_text(encoding='utf-8'))
test_text = (root/'test-cases.yaml').read_text(encoding='utf-8')
assert len(profile['rules']) == 26
assert profile['profiles'][0]['profile_id'] == 'P-AAS'
for test_id in [f'AAS-T{i:03d}' for i in range(1, 20)]:
    assert test_id in test_text
```

Expected: workflow fails because the two assets do not exist.

- [ ] **Step 2: Commit the existing generated Profile instance and Test Case YAML**

Use the already validated V1 assets without changing rule/test semantics.

- [ ] **Step 3: Run the workflow**

Expected: machine asset CI passes and reports 26 rules/39 tests.

---

### Task 2: Add the synthetic automotive AAS subject and loader

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/__init__.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/sample.py`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/aas-environment.json`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/capabilities.json`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/semantic-dictionary.json`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/supplementary/manual.txt`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/supplementary/program-version-note.txt`
- Create: `reference-implementation/p-aas-v1/examples/automotive-eol-station/supplementary/certificate.txt`
- Test: `reference-implementation/p-aas-v1/tests/test_sample.py`

**Interfaces:**
- Produces: `SampleBundle` with `environment`, `capabilities`, `semantic_dictionary`, `supplementary_dir`, `aas_id`, `submodel_ids`.

- [ ] **Step 1: Write failing fixture-loader tests**

```python
class SampleTests(unittest.TestCase):
    def test_load_sample_has_one_instance_asset_and_five_submodels(self):
        sample = load_sample(EXAMPLE_DIR)
        self.assertEqual('Instance', sample.aas['assetInformation']['assetKind'])
        self.assertTrue(sample.aas['assetInformation']['globalAssetId'])
        self.assertEqual(5, len(sample.environment['submodels']))

    def test_sample_uses_synthetic_namespace_only(self):
        sample = load_sample(EXAMPLE_DIR)
        text = json.dumps(sample.environment, ensure_ascii=False)
        self.assertIn('urn:example:automotive:', text)
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m unittest reference-implementation/p-aas-v1/tests/test_sample.py -v
```

Expected: import/file failure.

- [ ] **Step 3: Implement `SampleBundle` and `load_sample()`**

```python
@dataclass(frozen=True)
class SampleBundle:
    root: Path
    environment: dict
    capabilities: dict
    semantic_dictionary: dict

    @property
    def aas(self) -> dict:
        return self.environment['assetAdministrationShells'][0]

    @property
    def aas_id(self) -> str:
        return self.aas['id']
```

Loader must reject malformed JSON and missing top-level keys.

- [ ] **Step 4: Create the synthetic subject**

Use IDs under `urn:example:automotive:*` and five Submodels: Status, SoftwareVersion, ProcessParameters, Alarm, Documentation. Key properties must carry `semanticId`; parameter ConceptDescriptions must carry IEC61360-style metadata and unit references.

- [ ] **Step 5: Run tests and commit**

Expected: sample tests pass.

---

### Task 3: Implement structural and semantic checks for AAS-T002..T009

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/rules.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/semantic.py`
- Test: `reference-implementation/p-aas-v1/tests/test_rules.py`
- Test: `reference-implementation/p-aas-v1/tests/test_semantic.py`

**Interfaces:**
- Produces: `CheckResult(check_id: str, passed: bool, message: str, observed: object)`.
- Exposes: `check_asset_kind`, `check_asset_identifier`, `check_required_semantics`, `check_capabilities`, `check_iec61360`, `check_languages`, `check_units`, `check_unit_resolvability`.

- [ ] **Step 1: Write red tests for T002/T003/T009**

```python
self.assertTrue(check_asset_kind(sample).passed)
self.assertTrue(check_asset_identifier(sample).passed)
self.assertTrue(check_capabilities(sample, {'read_aas','read_submodel','query','authorization','signed'}).passed)
```

Add negative copies with missing identifier/capability and assert `passed == False`.

- [ ] **Step 2: Implement minimal structural checks and verify green**

`check_asset_identifier` passes only when non-empty `globalAssetId` exists or `specificAssetIds` contains at least one entry.

- [ ] **Step 3: Write red semantic tests for T004..T008**

Positive sample must pass. Negative mutations must independently fail missing semanticId, missing IEC61360 data specification, missing `en`, mismatched unit/unitId and unknown unitId.

- [ ] **Step 4: Implement semantic traversal helpers**

```python
def iter_submodel_elements(environment: dict):
    for submodel in environment.get('submodels', []):
        for element in submodel.get('submodelElements', []):
            yield submodel, element
```

Implement checks as pure functions with no I/O.

- [ ] **Step 5: Run structural/semantic suite and commit**

Expected: all positive and mutation tests pass.

---

### Task 4: Implement ABAC and JWS reference mechanics for AAS-T016/T017

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/policy.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/jws.py`
- Test: `reference-implementation/p-aas-v1/tests/test_policy_jws.py`

**Interfaces:**
- `evaluate_abac(subject: dict, resource: dict, context: dict) -> Decision`
- `sign_compact(payload: bytes, secret: bytes) -> str`
- `verify_compact(token: str, secret: bytes) -> tuple[bool, bytes | None]`

- [ ] **Step 1: Write ABAC red tests**

Allow when `subject.factory == resource.factory`, role is `engineer`, time is inside configured window and equipment state is `READY`. Deny each mismatch with a stable reason code.

- [ ] **Step 2: Implement deterministic policy evaluator**

Return `Decision(allowed, reason_code, attributes)`; never hide the reason in free-form logs only.

- [ ] **Step 3: Write JWS red tests**

```python
token = sign_compact(b'{"id":"aas-1"}', b'synthetic-secret')
ok, payload = verify_compact(token, b'synthetic-secret')
self.assertTrue(ok)
self.assertEqual(b'{"id":"aas-1"}', payload)
self.assertFalse(verify_compact(tamper(token), b'synthetic-secret')[0])
```

- [ ] **Step 4: Implement compact HS256 JWS with URL-safe base64**

Header must be `{"alg":"HS256","typ":"JWT"}` with compact `header.payload.signature` form. Use `hmac.compare_digest`.

- [ ] **Step 5: Run tests and commit**

Expected: allow/deny and tamper tests green.

---

### Task 5: Implement AASX builder/checker for AAS-T018/T019

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/aasx.py`
- Test: `reference-implementation/p-aas-v1/tests/test_aasx.py`

**Interfaces:**
- `build_aasx(sample: SampleBundle, destination: Path) -> Path`
- `validate_aasx(path: Path, required_supplementary: set[str]) -> list[CheckResult]`

- [ ] **Step 1: Write red package tests**

Build into a temporary path, open with `zipfile.ZipFile`, assert the generated package contains `[Content_Types].xml`, `_rels/.rels`, `aasx/aasx-origin`, `aasx/aas-environment.json` and three supplementary files.

- [ ] **Step 2: Implement package writer**

Create OPC relationship XML using `xml.etree.ElementTree`; do not commit generated ZIP/AASX.

- [ ] **Step 3: Implement validator and corruption tests**

Validate relationship targets exist. Create corrupted temporary copies missing `aasx-origin` or a supplementary relationship and assert failure.

- [ ] **Step 4: Run tests and commit**

Expected: T018/T019 mechanics green.

---

### Task 6: Implement embedded reference HTTP service and client for AAS-T010..T017

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/mock_server.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/api.py`
- Test: `reference-implementation/p-aas-v1/tests/test_api.py`

**Interfaces:**
- `ReferenceServer(sample, secret).start() -> RunningServer(base_url, stop)`
- `request_json(method, url, body=None, token=None) -> HttpResult`

- [ ] **Step 1: Write red endpoint tests**

Required reference endpoints:

```text
POST /query
GET  /shells/{id}
GET  /submodels/{id}
GET  /protected
PUT  /resources/{id}
POST /authorize
GET  /signed/{aas-id}
```

- [ ] **Step 2: Implement AAS/submodel/query endpoints**

Valid query `{"idShort":"Status"}` returns Status Submodel; malformed JSON or unsupported schema returns 400.

- [ ] **Step 3: Implement 401/403 and CREATE/UPDATE privilege behavior**

Synthetic tokens:
- `reader-token`
- `create-token`
- `update-token`
- `no-privilege-token`

No Authorization -> 401. Authenticated/no right -> 403. Create non-existing resource with create token -> 201. Update existing resource with update token -> 200.

- [ ] **Step 4: Wire ABAC and signed endpoints**

`POST /authorize` calls `evaluate_abac`; `GET /signed/{aas-id}` returns compact JWS from `jws.py`.

- [ ] **Step 5: Add transport client and verify tests**

`HttpResult` records status, parsed JSON if possible and bounded body text. Network failures raise a typed `TransportError` so the runner can mark tests `BLOCKED`.

- [ ] **Step 6: Run API suite and commit**

Expected: query/read/auth/PUT/ABAC/signature endpoint tests green.

---

### Task 7: Build Evidence Bundle and the AAS-T001..T019 orchestrator

**Files:**
- Create: `reference-implementation/p-aas-v1/paas_ref/evidence.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/runner.py`
- Create: `reference-implementation/p-aas-v1/paas_ref/__main__.py`
- Create: `reference-implementation/p-aas-v1/run_reference.py`
- Test: `reference-implementation/p-aas-v1/tests/test_evidence_runner.py`

**Interfaces:**
- `TestResult` with `test_id`, `level`, `result`, `linked_rule_ids`, `assertions`, `artifacts`, `observations`.
- `run_reference(example_dir, output_dir, external_base_url=None) -> dict`.

- [ ] **Step 1: Write red end-to-end test**

```python
bundle = run_reference(EXAMPLE_DIR, temp_out)
self.assertEqual(19, len(bundle['test_results']))
self.assertEqual([f'AAS-T{i:03d}' for i in range(1, 20)], sorted_ids(bundle))
self.assertTrue(all(r['result'] == 'PASS' for r in bundle['test_results']))
```

Also assert every artifact file is hashed with SHA-256 and the evidence bundle contains no private Drive URL.

- [ ] **Step 2: Implement evidence helpers**

Create artifact entries only after writing files; compute SHA-256 from bytes on disk.

- [ ] **Step 3: Implement T001 and local T002..T009 mapping**

T001 checks all P-AAS rules contain a source, machine check and test references. Map pure function outcomes to evidence assertions.

- [ ] **Step 4: Implement API T010..T017 mapping**

Default mode starts embedded server on port `0`. Transport failures become `BLOCKED`; unexpected statuses become `FAIL`.

- [ ] **Step 5: Implement AASX T018/T019 mapping**

Build `sample.aasx`, validate structure and supplementary relationships, record package SHA-256.

- [ ] **Step 6: Write `evidence-bundle.json` and `test-summary.json`**

Summary includes counts for PASS/FAIL/BLOCKED/N/A and overall status. Return non-zero CLI exit if any required test is FAIL/BLOCKED.

- [ ] **Step 7: Run end-to-end test and commit**

Expected: embedded reference subject yields 19/19 PASS.

---

### Task 8: Add documentation and CI acceptance

**Files:**
- Create: `reference-implementation/p-aas-v1/README.md`
- Create: `.github/workflows/validate-p-aas-reference.yml`
- Modify: `machine-readable/v1/README.md`

**Interfaces:**
- Produces: repeatable local/CI command and a one-day reference evidence artifact.

- [ ] **Step 1: Document local execution**

README must contain:

```bash
python -m unittest discover -s reference-implementation/p-aas-v1/tests -v
python reference-implementation/p-aas-v1/run_reference.py --out ./out/p-aas-reference
```

and Windows PowerShell equivalents that use the same Python commands.

- [ ] **Step 2: Document external-target mode**

Explain `--base-url` and token environment variables. State clearly that V1 external mode tests only operations represented in P-AAS V1, not complete IDTA certification.

- [ ] **Step 3: Add Public Actions workflow**

Workflow uses `ubuntu-latest`, no secrets, runs unit tests and full embedded reference execution, then uploads only generated evidence/AASX as `retention-days: 1` artifact.

- [ ] **Step 4: Add repository hygiene checks**

CI fails if committed source contains `.pdf`, `.aasx`, `drive.google.com`, or obvious private-secret fixture patterns under the new reference area.

- [ ] **Step 5: Run PR CI**

Expected:
- machine-readable metadata validation PASS;
- P-AAS unit suite PASS;
- reference run reports `AAS_PASS=19 AAS_FAIL=0 AAS_BLOCKED=0`;
- one-day artifact created from generated output only.

- [ ] **Step 6: Merge after verification**

Merge only after the PR head SHA's current workflow runs are green and the generated artifact is downloadable/inspectable.
