# Archive Workflow

## Operating model

`Official public source -> Public GitHub Actions runner -> one-day artifact -> Google Drive long-term archive`

GitHub is only the temporary network/compute relay. Google Drive is the authoritative long-term asset store.

## ChatGPT plugin queue

Direct HTTPS jobs enter `QUEUED`. Name- or number-only jobs remain `RESOLVING` until web Chat submits reviewed official/public sources through `resolve_download_sources`. When a job first enters `QUEUED`, a private repository-scoped GitHub App immediately dispatches the executor workflow. If App dispatch fails, the durable job remains queued for the existing five-minute repository-, branch-, and workflow-bound OIDC polling path. A successful byte/hash/Drive-verified upload completes automatically; no PAT, descriptor commit, content permission, or manual finalize call is part of normal operation.

All destinations are relative to the plugin-owned Drive folder `下载`. For example, `Google Drive/A/B` is archived as `下载/A/B`. Absolute paths, traversal, control characters, paths deeper than eight segments and segments longer than 100 characters are rejected.

Production jobs use state kind `download_job`; staging jobs use `download_job_staging`. Staging jobs are intentionally invisible to the production queue.

Release downloads in gates of 1, 10, 50 and 200 items. Do not advance a gate unless every prior job has a non-zero byte count, a valid SHA-256, independently verified Drive metadata, the expected nested parent and a terminal non-pending state.

## Generic source transfer

Download Executor 0.4 chooses a transfer path from HTTP capabilities and verified metadata, never from a provider name:

- sources with a known positive size keep the direct Drive resumable path; partial Range resume requires an independently supplied expected SHA-256 so an old prefix cannot be joined to a changed source;
- sources whose size cannot be established by `HEAD`, `Content-Length` or `Content-Range` return the machine-readable code `SOURCE_SIZE_UNKNOWN` and use the existing native/browser fallback chain;
- a successful fallback download becomes one local, size- and SHA-256-verified snapshot; Drive upload reads that same file and never fetches the source URL again. Partial staged resume requires a matching persisted session/snapshot checkpoint; and
- static PDFs, GitHub release assets, object storage, CDNs, chunked responses and dynamic APIs therefore share the same executor without host-specific branches.

Unknown-length staging consumes temporary runner disk space. The one-day GitHub artifact remains recovery evidence only; Google Drive remains the authoritative archive after readback verification.

Native source access failures, including an HTML landing/challenge page instead of an expected PDF/ZIP/GGUF, may use the configured browser fallback before upload has accepted any bytes. Length, binary magic and expected-hash integrity failures never fall back or finalize a truncated file. A resume whose content identity cannot be proven fails explicitly and must retry with a new upload session.

The Drive gateway independently reads Google's `sha256Checksum`, file ID, name, size, parent and trashed state. Completion requires the server-computed checksum to equal the executor's SHA-256. Successful receipts retain `drive_sha256`, `checksum_verified=true` and `checksum_method=google_drive_sha256`. Missing or mismatched cloud checksums fail closed and are submitted as terminal, retryable failures. This is independent provider checksum verification, not a full byte re-download through the Edge Function. Completed resumable sessions must retain their file ID and cloud checksum.

The executor verifies at most 20 Drive receipts per Edge request and refreshes OIDC for every verification batch. A failed batch cannot mark its files verified; successful batches retain their individual cloud evidence. This bounds verification requests without restricting the source provider, file type or per-file byte size.

## Adding a public asset to the legacy manifest pipeline

These steps describe the manifest/artifact connector pipeline, not the ChatGPT plugin's direct resumable path above.

1. Confirm that the source is official/public and redistribution is permitted.
2. Add one entry to `manifest/standards.json`.
3. Set `redistributable` to `true` only when automatic archival is allowed.
4. Supply `expected_size_bytes` when known so CI can reject an artifact group that would exceed the Drive transfer ceiling.
5. If the source itself is too large, set `split_parts` to an integer that keeps each part below 95 MiB.
6. Commit the manifest change; CI validates and downloads the source.
7. Transfer successful GitHub Actions artifacts to the matching logical Drive folder.
8. Update `archive/drive-status.json` with logical path/status only. Never commit Drive file IDs or private URLs.

## Evidence

Every transfer artifact includes `evidence.csv` with:

- stable asset ID;
- official source URL;
- expected and actual byte sizes;
- source SHA-256;
- output filename and SHA-256;
- split part index/total where applicable;
- success/failure diagnostics.

Split artifacts also contain `reconstruct.json` with the exact ordered part list and reconstruction commands.

## Copyright-restricted standards

Do not add direct full-text download entries for copyright-restricted ISO, IEC, IATF, AIAG, VDA, SAE or equivalent publications unless the specific source/license explicitly permits redistribution. Track those standards through official acquisition links and research metadata instead.

## Cost controls

- Repository: public.
- Runner: `ubuntu-latest` only.
- Artifact retention: one day.
- No release assets for downloaded standards.
- No standards binaries in Git commits.
- No redundant complete-bundle artifact.

## Legacy connector transfer ceiling

The legacy connector path rejects a single transfer object above 100 MiB and uses a 95 MiB payload guard with deterministic multi-part transfer. The ChatGPT plugin bypasses that connector using authenticated Drive resumable uploads; its limit is runner/runtime/storage capacity, not the legacy 95 MiB guard. Unknown-length sources and browser snapshots additionally need local disk/memory capacity. Capacity gates of 50, 200 and full-catalog downloads remain separate from functional bug-fix acceptance.

