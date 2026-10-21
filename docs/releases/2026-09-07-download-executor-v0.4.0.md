# Download executor 0.4.0 release

Released 2026-09-07. The product remains a generic ChatGPT download plugin with Supabase control/Drive gateways and GitHub App-dispatched execution, not a skill or a provider-specific downloader.

## Revisions and verification

- Implementation: `9ae28b21eb5aa8dc6ab0c6b0654423de098ed509`.
- Bounded cloud-verification follow-up: `538c50255bb5d018c8b3f37610262ca1058d455d`.
- Supabase `download-drive`: version 8 ACTIVE; staging version 11. Existing `download-mcp` version 11 and authentication scopes are unchanged.
- [CI 34082649435](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/34082649435): 48 executor/workflow tests, two actual Chromium/helper integration tests and 52 Node contracts passed. Browser cases use a controlled HTTPS origin and HTTP Drive fixture, not a substituted browser process.
- Independent read-only code review found no remaining blockers within this repair scope.

## Closed defects

The executor rejects inconsistent lengths, ranges, EOF, binary magic and expected hashes before final upload. Recoverable source failures and HTML challenge pages may reach browser fallback before any bytes are accepted. Complete sessions retain their file IDs and provider checksums. Partial direct resume requires an expected SHA-256; partial staged resume requires a matching session/snapshot checkpoint. Unprovable identity fails safely rather than joining different source versions.

The gateway independently compares Google's `sha256Checksum`, ID, name, size, parent and trashed state. Receipts retain `drive_sha256`, `checksum_verified` and `checksum_method=google_drive_sha256`. This is independent provider checksum verification, not a full Edge-mediated byte re-download.

OIDC is refreshed after long transfers and per verification batch. Malformed/failed verification is normalized into reportable failure. Verification requests contain at most 20 receipts; a failed batch does not erase valid evidence from successful batches. A 132-file single-request timeout observed during release prompted this last generic fix.

## Fresh production evidence

| Gate | Evidence | Result |
| --- | --- | --- |
| Unknown-length dynamic snapshot | [Run 34083138695](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/34083138695), 2142-byte public repository JSON, `drive-resumable-local` | COMPLETED, independent cloud checksum matched |
| Controlled ten-file batch | [Run 34083247468](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/34083247468), NIST AI RMF PDF, public arXiv paper, Qwen GGUF and seven RFC texts | 10 PASS, zero FAIL, all ten cloud checksums matched |
| Large source | Same ten-file run, Qwen GGUF, 415182688 bytes, SHA-256 `9ee36184e616dfc76df4f5dd66f908dbde6979524ae36e6cefb67f532f798cb8` | Direct resumable upload, no legacy connector split |
| Real multi-batch verification | [Run 34082784164](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/34082784164), existing 90-file queue job, offsets 0/20/40/60/80 all HTTP 200 | 90 PASS, zero FAIL, independently verified |

Evidence including private Drive references is retained outside the public repository. No downloaded binaries or credentials were committed. Local and remote production history is aligned; the former local branch remains archived rather than deleted.

## Boundaries and rollback

This closes the audited functional repair and controlled backend release gates. A fresh ChatGPT UI test was not completed because browser control repeatedly timed out; previous UI evidence must not be presented as new. Dedicated Work UI, 200-file and full-catalog capacity acceptance remain separate. A successful existing 90-file batch does not prove arbitrary providers or unbounded concurrency. Earlier failed/historical jobs were not mass-retried, cancelled or cleaned up.

Rollback references: prior executor `81539f25837ddcc188883672160ce7d2a3151b47`; prior Drive gateway version 7 source captured locally before deployment. Restore the captured gateway file set and previous workflow/executor sources through a reviewed forward change; do not force-reset shared history or alter credentials. See [operating model](../ARCHIVE_WORKFLOW.md) for source policy, destination safety and the distinct legacy connector ceiling.
