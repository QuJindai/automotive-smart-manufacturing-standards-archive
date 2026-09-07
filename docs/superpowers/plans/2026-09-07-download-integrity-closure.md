# Generic download integrity closure

Scope: close the audited executor/Drive defects while preserving the generic public-source plugin, existing GitHub App dispatch, safe destinations, permissions and production queue. No provider-specific routing or dataset analysis.

## Implementation and regression evidence

- [x] Reproduce short expected-size truncation, missing known-size source fallback and lost completed-session receipts before fixing them.
- [x] Reject Content-Length/Range/EOF/expected-SHA inconsistencies before final Drive PUT.
- [x] Permit recoverable source failures and HTML challenge pages to reach native/browser fallback without masking binary integrity failures.
- [x] Retain completed-session file IDs and validate the provider receipt checksum.
- [x] Prevent mixed-version partial resume: expected SHA for direct sources; persisted session/snapshot identity for staged files.
- [x] Compare independently fetched Google Drive SHA-256, size, filename and parent; persist the independent evidence.
- [x] Convert Drive verification errors into reportable terminal failures; refresh short-lived OIDC credentials after downloads.
- [x] Preserve static formats, redirects, no-Range, unknown-length dynamic snapshot, large multi-chunk and safe resume coverage.
- [x] Run local suites: Python 48 passed, two browser-only cases skipped; Node 52 passed. The production shell/normalizer is exercised for OIDC refresh failure and malformed gateway JSON as well as success/failure receipts.
- [x] Run the two real Chromium/helper cases in Linux CI, not a mocked browser: CI 34082649435, both passed; total unique executed tests 102.
- [x] Deploy reviewed gateway sources with rollback captured and release the executor only after green CI: download-drive v8, executor commits 9ae28b2 and 538c502.
- [x] Prove fresh production static and unknown-length jobs with matching independent Drive SHA-256: runs 34083138695 and 34083247468.
- [x] Prove a fresh production file larger than 100 MiB: official Qwen GGUF, 415182688 bytes, independent Drive SHA-256 matched.
- [x] Complete a controlled 10-file production batch and record durable evidence: run 34083247468, 10 PASS, zero FAIL.
- [x] Fix the observed 132-file single-request verification timeout with bounded batches; verify real 90-file completion in run 34082784164 and 20/20/1 success/partial-failure regression cases.
- [x] Record deployed revision, function versions and exact release gates in [the final release note](../../releases/2026-09-07-download-executor-v0.4.0.md).

The 2026-08-30 and 2026-08-31 plans remain historical design/implementation records. Their original unchecked procedural steps are not evidence that deployed code is missing, nor evidence that every historical UI/capacity test passed. This checklist and its final release note supersede their completion status for this repair. Dedicated Work UI acceptance and 50/200/full-catalog load gates must not be inferred from backend or 10-file results.
