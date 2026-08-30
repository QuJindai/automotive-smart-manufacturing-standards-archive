# Download Plugin Autonomous Closure Design

## Objective

Make the personal ChatGPT plugin `下载` complete a legal public download without Codex or another human operator committing a GitHub descriptor, finalizing the job, or moving the Drive file. The two release gates are:

1. an official direct HTTPS URL reaches verified Google Drive persistence; and
2. a standards name or number is resolved by the ChatGPT host to an official/public URL and then reaches the same verified persistence path.

The first production samples are the existing IDTA direct-URL job `download-d57308b96f1b42ad8a128a31a60421f2` and a new standards-number job created from web Chat.

## Confirmed production gaps

The current control plane intentionally delegates work that web Chat cannot perform:

- requests without URLs stop at `host.resolve_download_sources`;
- requests with URLs stop at `COMMIT_GITHUB_DESCRIPTOR` and require `github.write`;
- the executor workflow runs only after a push under `.download/jobs/**`;
- a verified direct Drive upload stops at `FINALIZE` instead of completing automatically; and
- `download-drive` ignores the requested destination and always writes into the plugin root folder `下载`.

The byte-transfer implementation is not the root cause. `scripts/download_executor.py` already validates PDF/GGUF/ZIP magic, records exact byte size, computes SHA-256, supports native/browser fallback, streams through resumable Drive sessions, and verifies the resulting Drive metadata.

## Scope

### Included

- source-resolution result submission as a first-class MCP tool;
- secretless GitHub Actions queue polling with OIDC-authenticated claiming;
- automatic completion after verified Drive persistence;
- safe nested folders below the plugin-owned Drive root;
- source-controlled Supabase function code and unit contracts;
- migration/recovery behavior for the two currently blocked jobs; and
- production acceptance in web Chat and Work.

### Excluded

- downloading non-public ISO, IEC, IATF, AIAG, VDA, SAE or other restricted full texts;
- bypassing login, paywalls, DRM, robots restrictions, or anti-bot interstitials;
- arbitrary Drive locations outside the plugin-owned `下载` root;
- a general-purpose search engine inside Supabase Edge Functions; and
- bulk release above ten standards before both single-item gates pass.

## Approaches considered

### Selected: OIDC queue polling plus host-assisted source resolution

GitHub Actions polls a protected queue endpoint on a five-minute schedule. It obtains a GitHub OIDC token, atomically claims one queued job, and runs the existing executor. Web Chat uses its native web research capability to locate official/public sources, then submits those sources through a dedicated MCP tool.

This preserves the existing trust boundary: GitHub owns compute, Supabase owns job state and authorization, Drive owns durable files, and no long-lived GitHub token is added to Supabase.

### Rejected: Supabase-held GitHub personal access token

Calling `workflow_dispatch` would reduce queue latency, but it introduces a long-lived repository credential, rotation burden, and a larger blast radius. It is not required for the first production release.

### Rejected: run all downloads inside Supabase Edge Functions

This would remove GitHub from the path but conflicts with large-file, browser-fallback, execution-time and memory requirements. It would duplicate the tested executor and weaken recovery.

## Architecture

### Control plane: `download-mcp`

The production function becomes source-controlled under `supabase/functions/download-mcp/` and exposes six MCP tools:

- `start_download`
- `resolve_download_sources`
- `get_download`
- `resume_download`
- `retry_download`
- `finalize_download`

`resolve_download_sources` accepts:

```json
{
  "download_id": "download-...",
  "sources": [
    {
      "requested_item": "IDTA AAS Part 1 Metamodel",
      "source_url": "https://official.example/specification.pdf",
      "filename": "specification.pdf",
      "license_class": "open-specification",
      "redistributable": true,
      "official": true,
      "expected_size_bytes": 12345,
      "expected_sha256": "optional-lowercase-hex"
    }
  ],
  "unresolved": [
    {
      "requested_item": "restricted standard",
      "reason": "No legal public full text was found",
      "official_catalog_url": "https://official.example/catalog-entry"
    }
  ]
}
```

The function independently revalidates every URL as HTTPS and non-private, re-runs the access-control policy, limits a job to 20 resolved sources, rejects duplicate URLs/filenames, and validates optional size/hash fields. `redistributable` and `official` are recorded provenance assertions, not substitutes for byte validation.

If at least one source resolves, the job enters `QUEUED`. If none resolve, it enters `BLOCKED` with explicit unresolved reasons and no executor action. Resubmitting an identical resolution is idempotent; a conflicting resolution is rejected unless the job is still `RESOLVING`.

### Queue claim interface

`POST /executor/claim` is accessible only to the existing GitHub OIDC identity for the repository, `main` ref and `download-executor.yml` workflow. It:

1. reads the oldest eligible `QUEUED` job;
2. permits reclaim when a previous claim lease expired;
3. applies an optimistic revision update;
4. stores `executor.status=CLAIMED`, claim timestamp and a 20-minute lease; and
5. returns the selected `download_id`, or HTTP 204 when no work exists.

Only one job is claimed per workflow run. A job may contain multiple assets. This is sufficient for the 1-, 10- and 50-standard gates without introducing a matrix scheduler. Queue throughput is reconsidered before the 200-standard gate.

### GitHub executor workflow

`.github/workflows/download-executor.yml` keeps the push trigger for recovery and adds:

- `schedule: cron: '*/5 * * * *'`;
- `workflow_dispatch` for operator recovery; and
- an OIDC-first job-selection step.

For a push event, the workflow reads the existing descriptor exactly as today. For schedule/manual events, it calls `/executor/claim`. HTTP 204 produces a successful no-op run. When a job is returned, all existing payload fetch, Drive-session, download, magic/hash, readback and result-submission steps execute unchanged.

### Automatic finalization

When executor results contain at least one passed asset, no failed assets, verified Drive references for every passed asset, and `drive_verified=true`, `download-mcp` writes `COMPLETED` in the same optimistic state transition. It does not return another host action.

`finalize_download` remains for recovery and partial-approval workflows, but normal successful downloads do not require a second model/tool call.

### Drive destination semantics

The plugin retains one app-owned Drive root folder named `下载`. User destinations are interpreted only as relative paths below that root.

- Optional leading segments `Google Drive` and `下载` are removed.
- Both `/` and `\` separators are accepted.
- Empty segments and `.` are normalized away.
- `..`, absolute paths, control characters, segments longer than 100 characters, and depth above eight are rejected.
- Missing folders are created one segment at a time below the current parent.
- Folder reuse requires an exact name, folder MIME type, non-trashed state and matching parent.
- Upload sessions target the resolved leaf folder.
- Drive verification requires the file parent to equal the expected leaf folder.

Thus `Google Drive/汽车智能制造标准研究_2026/下载插件验收_20260830/` resolves to `下载/汽车智能制造标准研究_2026/下载插件验收_20260830/`.

## Job state model

```text
PLANNED
  -> RESOLVING        request contains no direct HTTPS source
  -> QUEUED           direct source exists

RESOLVING
  -> QUEUED           at least one legal/public source submitted
  -> BLOCKED          no legal/public source resolved

QUEUED
  -> FETCHING         GitHub OIDC worker claims the job

FETCHING
  -> COMPLETED        bytes, magic, SHA-256, Drive upload and readback all pass
  -> PARTIAL          at least one asset passes and at least one fails
  -> FAILED           every asset fails
  -> AUTH_REQUIRED    Drive authorization is unavailable

FAILED/PARTIAL/AUTH_REQUIRED
  -> QUEUED           explicit retry after the blocker is corrected
```

Every transition updates `current_stage`, `last_verified_stage`, `status`, `updated_at`, `next_action`, `blocker` and executor lease fields consistently.

## Web Chat behavior

The MCP server instructions and tool descriptions tell the model to continue rather than report an intermediate host action:

1. If the user supplied direct URLs, call `start_download` and report that the job is queued.
2. If the user supplied names/numbers, call `start_download`, research official/legal public sources, then call `resolve_download_sources` on the same job.
3. Poll `get_download` only when the user is waiting in the conversation; otherwise return the durable `download_id` and explain the queue interval.
4. Never claim completion until `status=COMPLETED` and `drive_verified=true`.

The tool result schemas include job ID, state, counts, unresolved items, Drive references and retryability so ChatGPT no longer shows the current output-schema warning.

## Security and policy

- The private MCP path remains unchanged and is never written to Git or user-visible output.
- Executor endpoints retain exact repository/ref/workflow OIDC checks.
- Queue claims use optimistic revisions and leases to prevent duplicate execution.
- Source URLs are redacted in logs; query strings and credentials are never returned in executor evidence.
- Private-network, localhost and metadata targets remain blocked.
- Requests to bypass access or copyright controls remain blocked before job creation and source submission.
- Drive OAuth tokens and resumable session URLs remain encrypted or ephemeral and never enter repository artifacts.
- GitHub descriptors continue to contain only `download_id`.

## Failure and recovery

- A workflow crash leaves a claim that becomes eligible after 20 minutes.
- An empty queue is a successful workflow no-op.
- A source-resolution conflict is explicit and does not overwrite prior assets.
- A failed asset records the attempted method and error, while verified Drive files are preserved.
- Retry increments the fallback index and re-enters `QUEUED`; it does not redownload passed assets.
- The existing IDTA direct-URL task is migrated from `FETCHING` with no executor to `QUEUED` after deployment.
- The existing four-standard unresolved task remains `RESOLVING` so web Chat can submit a reviewed resolution set rather than silently accepting guessed URLs.
- Rollback redeploys the previous Supabase function versions and reverts the workflow commit; durable job rows and Drive files are retained.

## Source layout

The repository becomes the recoverable source of truth for the deployed functions:

```text
supabase/functions/download-mcp/index.ts
supabase/functions/download-mcp/core.ts
supabase/functions/download-drive/index.ts
supabase/functions/download-drive/path.ts
tests/download_mcp/core_test.ts
tests/download_drive/path_test.ts
.github/workflows/download-executor.yml
.github/workflows/download-executor-ci.yml
```

Pure state, URL and path logic lives outside request handlers so tests exercise real production functions without network mocks.

## Test strategy

### Unit contracts

- direct URL creates a `QUEUED` job;
- name/number-only request creates `RESOLVING`;
- resolved official HTTPS sources move the same job to `QUEUED`;
- private/non-HTTPS/duplicate/conflicting sources are rejected;
- queue selection is oldest-first and expired leases are reclaimable;
- successful verified executor results become `COMPLETED` automatically;
- incomplete Drive evidence cannot become `COMPLETED`;
- destination normalization and traversal/depth/length rejection;
- expected Drive leaf-parent verification; and
- current PDF/GGUF/ZIP magic, SHA-256, fallback and URL-redaction contracts remain green.

Each behavior change follows red-green testing: the new contract is observed failing against the current implementation before production code is added.

### Production gates

1. **Direct URL gate:** migrate the existing IDTA job, allow the scheduled worker to claim it without a descriptor commit, and require PDF header, exact size, SHA-256, Drive file ID, expected nested parent and Drive readback.
2. **Standards-number gate:** in a fresh web Chat conversation, request one known open standard by name/number with no URL. Chat must research an official source, call `resolve_download_sources`, and reach the same completion evidence.
3. **Work regression:** query and start one legal public sample through Work.
4. **Negative regression:** private address, paywall-bypass request, duplicate source, claim race, expired lease and invalid Drive path.

## Rollout gates

- Gate 0: unit/CI contracts and Supabase staging pass.
- Gate 1: one direct URL completes autonomously.
- Gate 2: one standard number completes autonomously.
- Gate 3: ten standards in one job, with zero unexplained pending jobs.
- Gate 4: fifty standards after reviewing GitHub runtime, Drive quota, source failure rate and queue latency.
- Gate 5: two hundred standards only after queue throughput is intentionally increased.
- Full corpus: permitted only after the 200-item report shows bounded failure/retry behavior and no restricted-text downloads.

## Acceptance criteria

The change is release-ready only when:

- web Chat requires no Codex or manual GitHub commit for either release gate;
- the production job reaches `COMPLETED` with `drive_verified=true`;
- every passed file has a non-empty SHA-256, exact byte size and Drive file ID;
- PDFs pass `%PDF-` magic validation and HTML error pages fail;
- the Drive file exists in the normalized requested leaf folder;
- no relevant Supabase/GitHub run ends with an unexplained 5xx or hanging claim;
- rejected policy/security tests create no dirty jobs; and
- the previous executor and large-file regression suite remains green.

