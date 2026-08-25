# Public Standards Download Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a public, manifest-driven GitHub Actions relay that downloads redistributable standards assets, validates them, emits SHA-256 evidence, splits oversized assets, and keeps artifacts for one day before long-term Drive archival.

**Architecture:** A JSON manifest is validated and converted to an Actions matrix. Matrix jobs fetch either a small artifact group or one deterministic part of a large source. The workflow uploads only short-lived artifacts; Git history contains no standards binaries.

**Tech Stack:** GitHub Actions, Python 3 standard library, curl on `ubuntu-latest`, JSON/CSV.

**Spec:** `docs/superpowers/specs/2026-08-25-public-standards-download-pipeline-design.md`

## Global Constraints

- Repository must remain public.
- Runner must be `ubuntu-latest`.
- Artifact retention must be exactly 1 day.
- No standards PDF/ZIP binaries may be committed to Git history.
- Only entries with `redistributable: true` may be automatically fetched.
- Per-artifact payload must be <= 95 MiB.
- Drive private file IDs/URLs must not be committed.

---

### Task 1: Manifest validator and matrix generator

**Files:**
- Create: `manifest/standards.json`
- Create: `scripts/prepare_matrix.py`
- Create: `tests/test_prepare_matrix.py`

**Interfaces:**
- Consumes: `manifest/standards.json`.
- Produces: JSON matrix object with `include[]` items containing either `{mode:"group", group, artifact_name}` or `{mode:"split", asset_id, part_index, part_total, artifact_name}`.

- [ ] **Step 1: Write tests for duplicate IDs, invalid URLs, non-redistributable entries, small groups and split entries.**
- [ ] **Step 2: Run `python -m unittest tests.test_prepare_matrix -v`; expect failures before implementation.**
- [ ] **Step 3: Implement manifest validation and deterministic matrix generation.**
- [ ] **Step 4: Re-run tests; expect all PASS.**
- [ ] **Step 5: Commit.**

### Task 2: Downloader, evidence manifest and split handling

**Files:**
- Create: `scripts/fetch_assets.py`
- Create: `tests/test_fetch_assets.py`

**Interfaces:**
- Consumes: validated manifest plus CLI args `--mode`, `--group` or `--asset-id`, `--part-index`, `--part-total`, `--out`.
- Produces: fetched files/part files plus `evidence.csv` containing id, filename, source_url, status, source_size_bytes, source_sha256, output_filename, output_size_bytes, part_index, part_total.

- [ ] **Step 1: Write unit tests for PDF/ZIP magic validation, deterministic byte slicing and payload-size checks using temporary local files.**
- [ ] **Step 2: Run `python -m unittest tests.test_fetch_assets -v`; expect failures.**
- [ ] **Step 3: Implement download, retry, magic/header validation, SHA-256, split output and 95 MiB payload guard.**
- [ ] **Step 4: Re-run tests; expect all PASS.**
- [ ] **Step 5: Commit.**

### Task 3: GitHub Actions workflow and archive metadata

**Files:**
- Create: `.github/workflows/fetch-public-assets.yml`
- Create: `archive/drive-status.json`
- Create: `docs/ARCHIVE_WORKFLOW.md`

**Interfaces:**
- Consumes: matrix JSON from Task 1 and fetcher from Task 2.
- Produces: one-day GitHub Actions artifacts suitable for connector transfer to Google Drive.

- [ ] **Step 1: Add a prepare job that runs all unit tests and emits the matrix.**
- [ ] **Step 2: Add a matrix fetch job on `ubuntu-latest` with `actions/upload-artifact@v4` and `retention-days: 1`.**
- [ ] **Step 3: Add `workflow_dispatch` and manifest/trigger-file push paths; do not require repository secrets.**
- [ ] **Step 4: Record the already archived initial logical Drive destinations without file IDs.**
- [ ] **Step 5: Commit.**

### Task 4: End-to-end CI acceptance

**Files:**
- Create: `.github/standards-download-trigger.txt`
- Update: `archive/drive-status.json` after successful transfer evidence.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: successful Actions run, artifacts <=95 MiB, SHA-256 evidence and stable reusable pipeline.

- [ ] **Step 1: Push a trigger update on the feature branch and open a PR to `main` so pull-request CI runs.**
- [ ] **Step 2: Inspect all workflow jobs; require prepare + every fetch matrix item to succeed.**
- [ ] **Step 3: Inspect artifact list and verify retention/artifact sizes are Drive-compatible.**
- [ ] **Step 4: Download at least the evidence/small artifact through the connector as an end-to-end probe.**
- [ ] **Step 5: Merge the PR only after CI succeeds.**

### Task 5: Cleanup legacy temporary runner

**Files:**
- Modify/Delete in `QuJindai/document-intelligence-benchmark`: temporary public-standards workflow/trigger only after the new repository passes acceptance.

**Interfaces:**
- Consumes: successful new-repo acceptance.
- Produces: one canonical public download infrastructure repository.

- [ ] **Step 1: Confirm new repository workflow is green.**
- [ ] **Step 2: Delete the temporary standards-download workflow and trigger from the old runner repository if still present.**
- [ ] **Step 3: Confirm no standards binaries were committed in either repository.**
