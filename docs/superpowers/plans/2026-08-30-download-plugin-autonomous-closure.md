# Download Plugin Autonomous Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `下载` ChatGPT plugin resolve public sources through web Chat, claim GitHub execution without a manual descriptor commit, write into a safe requested Drive subfolder, and complete automatically only after byte/hash/Drive verification.

**Architecture:** Supabase remains the durable control plane and exposes a source-resolution tool plus an OIDC-only queue claim endpoint. GitHub Actions polls that queue every five minutes and reuses the existing executor; Google Drive remains the durable store and resolves every destination below the app-owned `下载` root. Pure state/path logic is isolated in TypeScript modules that Node 24 can test directly before the Deno handlers are deployed.

**Tech Stack:** Supabase Edge Functions (Deno/TypeScript), PostgREST optimistic revisions, MCP 2025-06-18, GitHub Actions/OIDC, Python 3.12 executor, Node.js 24 test runner, Google Drive v3 resumable uploads.

**Spec:** `docs/superpowers/specs/2026-08-30-download-plugin-autonomous-closure-design.md`

## Global Constraints

- Preserve the current private MCP URL; commit only SHA-256 `04a7f402eeef7364d76701445f701ef278ce2c698469848db45ffe74bcd5c162`, never the raw path capability.
- Keep `verify_jwt=false` for `download-mcp` and `download-drive`; MCP path hashing and exact GitHub OIDC claims provide endpoint-specific authorization.
- Accept only HTTPS public-network sources; continue rejecting localhost, private IPv4 ranges, metadata hosts and access-control bypass requests.
- Do not download or redistribute restricted ISO, IEC, IATF, AIAG, VDA, SAE or equivalent full texts without explicit public redistribution evidence.
- Keep downloaded binaries out of Git history; descriptors contain exactly `download_id`; Actions artifacts retain for one day.
- Keep the existing `download-drive` OAuth scope `https://www.googleapis.com/auth/drive.file` and never expose OAuth tokens or resumable session URLs.
- Resolve every destination below the plugin-owned Drive root `下载`; never address an arbitrary existing Drive folder.
- Limit one job to 20 resolved sources, one claim per scheduled workflow run, an eight-segment destination and a 20-minute executor lease.
- Use `apply_patch` for repository edits and preserve unrelated files and user changes.
- Do not deploy production until unit tests, staging MCP contracts and rollback sources are captured.

---

## File map

- `supabase/functions/download-mcp/core.ts`: pure URL, policy, job-state, resolution, claim and executor-result transitions.
- `supabase/functions/download-mcp/index.ts`: Deno HTTP/MCP/PostgREST/JWT adapter; contains no raw private path token.
- `supabase/functions/download-drive/path.ts`: pure destination normalization and Drive query escaping.
- `supabase/functions/download-drive/index.ts`: Deno OAuth/Drive/OIDC adapter and nested-folder creation/readback.
- `tests/download_mcp/core.test.mjs`: Node 24 contracts for control-plane behavior.
- `tests/download_drive/path.test.mjs`: Node 24 contracts for Drive path safety.
- `tests/download_executor/test_queue_workflow.py`: repository contract for schedule, OIDC claim and no-op behavior.
- `.github/workflows/download-executor.yml`: push-compatible executor plus scheduled/manual queue consumer.
- `.github/workflows/download-executor-ci.yml`: Python, Node/TypeScript and workflow contract verification.
- `.github/workflows/download-plugin-staging-acceptance.yml`: six-tool staging MCP and policy contract.
- `docs/ARCHIVE_WORKFLOW.md`: operator behavior, queue latency, path semantics and rollout gates.

---

### Task 1: Source-control the MCP and establish initial job contracts

**Files:**
- Create: `supabase/functions/download-mcp/core.ts`
- Create: `supabase/functions/download-mcp/index.ts`
- Create: `tests/download_mcp/core.test.mjs`
- Modify: `.github/workflows/download-executor-ci.yml:5-22,32-40`

**Interfaces:**
- Consumes: the exact production `download-mcp` v5 source fetched with Supabase `get_edge_function`.
- Produces: `buildInitialJob(args, now, downloadId)`, `buildToolDefinitions()`, `jobOutputSchema`, `privatePathMatches(pathname)`.

- [ ] **Step 1: Write the failing initial-state tests**

```js
// tests/download_mcp/core.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildInitialJob,
  buildToolDefinitions,
  privatePathMatches,
} from "../../supabase/functions/download-mcp/core.ts";

const NOW = "2026-08-30T00:00:00.000Z";

test("direct HTTPS request creates a queued job without a GitHub host action", () => {
  const job = buildInitialJob(
    { request: "IDTA https://example.org/spec.pdf", destination: "Google Drive/验收" },
    NOW,
    "download-direct",
  );
  assert.equal(job.status, "QUEUED");
  assert.equal(job.current_stage, "QUEUED");
  assert.equal(job.assets.length, 1);
  assert.equal(job.next_action.action, "WAIT_EXECUTOR");
  assert.notEqual(job.next_action.action, "COMMIT_GITHUB_DESCRIPTOR");
});

test("name-only request creates a resolving job", () => {
  const job = buildInitialJob(
    { request: "GB/T 39116 智能制造能力成熟度模型" },
    NOW,
    "download-resolving",
  );
  assert.equal(job.status, "RESOLVING");
  assert.deepEqual(job.assets, []);
  assert.equal(job.next_action.action, "RESOLVE_SOURCES");
});

test("tool list exposes source resolution and output schemas", () => {
  const tools = buildToolDefinitions();
  assert.deepEqual(tools.map((tool) => tool.name), [
    "start_download",
    "resolve_download_sources",
    "get_download",
    "resume_download",
    "retry_download",
    "finalize_download",
  ]);
  assert.ok(tools.every((tool) => tool.outputSchema?.type === "object"));
});

test("private MCP path compares by hash without embedding the raw capability", async () => {
  assert.equal(await privatePathMatches("/mcp/not-the-capability"), false);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node --test tests/download_mcp/core.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `supabase/functions/download-mcp/core.ts`.

- [ ] **Step 3: Add the minimum pure initial-job implementation**

```ts
// supabase/functions/download-mcp/core.ts
export const PRIVATE_PATH_SHA256 =
  "04a7f402eeef7364d76701445f701ef278ce2c698469848db45ffe74bcd5c162";

export async function privatePathMatches(pathname: string): Promise<boolean> {
  const match = /^\/mcp\/([^/]+)$/.exec(pathname);
  if (!match) return false;
  const bytes = new TextEncoder().encode(match[1]);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const actual = [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return actual === PRIVATE_PATH_SHA256;
}

export function buildInitialJob(args: Record<string, unknown>, now: string, downloadId: string) {
  const request = requireText(args.request, "request");
  assertPolicy(request);
  const urls = extractUrls(request);
  const assets = urls.map((url, index) => buildAsset(url, index));
  const queued = assets.length > 0;
  return {
    download_id: downloadId,
    request,
    destination: typeof args.destination === "string" && args.destination.trim()
      ? args.destination.trim()
      : "Google Drive",
    constraints: isPlainObject(args.constraints) ? args.constraints : {},
    current_stage: queued ? "QUEUED" : "RESOLVING",
    last_verified_stage: queued ? "RESOLVING" : "PLANNED",
    status: queued ? "QUEUED" : "RESOLVING",
    assets,
    unresolved: [],
    pass_files: [],
    failed_files: [],
    drive_refs: [],
    drive_verified: false,
    next_action: queued
      ? { action: "WAIT_EXECUTOR", required: false, retry_after_seconds: 300 }
      : { action: "RESOLVE_SOURCES", required: true },
    blocker: null,
    executor: null,
    created_at: now,
    updated_at: now,
  };
}
```

Also export exact helpers `requireText`, `assertPolicy`, `safeUrl`, `extractUrls`, `buildAsset`, `isPlainObject`, `jobOutputSchema` and `buildToolDefinitions`. Define `jobOutputSchema` with required fields `download_id`, `status`, `current_stage`, `drive_verified`, `pass_files`, `failed_files`, `drive_refs`, `assets`, `unresolved`, `next_action` and `retryable`. Each tool uses that schema.

Create `supabase/functions/download-mcp/index.ts` from the fetched production v5 handler, replace the hard-coded path check with `await privatePathMatches(sub)`, import the pure functions, use `buildInitialJob` in `start`, and keep the existing PostgREST, redaction, executor OIDC and MCP response behavior unchanged.

- [ ] **Step 4: Run the control-plane tests and verify GREEN**

Run:

```powershell
node --test tests/download_mcp/core.test.mjs
```

Expected: 4 tests PASS and the repository contains no raw private capability:

```powershell
rg -n "PRIVATE_PATH_KEY|PRIVATE_MCP_PATH" supabase tests
```

Expected: no matches.

- [ ] **Step 5: Add the Node contract to CI**

Add `supabase/functions/download-mcp/**`, `supabase/functions/download-drive/**`, `tests/download_mcp/**` and `tests/download_drive/**` to both CI path filters. After `actions/setup-node@v4`, add:

```yaml
      - name: Run Supabase download control contracts
        run: node --test tests/download_mcp/*.test.mjs tests/download_drive/*.test.mjs
```

- [ ] **Step 6: Commit Task 1**

```powershell
git add supabase/functions/download-mcp tests/download_mcp .github/workflows/download-executor-ci.yml
git commit -m "feat: queue direct download jobs"
```

---

### Task 2: Add source-resolution submission and policy/idempotency contracts

**Files:**
- Modify: `supabase/functions/download-mcp/core.ts`
- Modify: `supabase/functions/download-mcp/index.ts`
- Modify: `tests/download_mcp/core.test.mjs`

**Interfaces:**
- Consumes: `buildAsset`, `safeUrl`, `assertPolicy`, job shape from Task 1.
- Produces: `applySourceResolution(job, input, now)` and MCP tool `resolve_download_sources`.

- [ ] **Step 1: Add one failing contract per resolution behavior**

```js
import { applySourceResolution } from "../../supabase/functions/download-mcp/core.ts";

test("official public resolution queues the same job", () => {
  const original = buildInitialJob(
    { request: "IDTA AAS Part 1 Metamodel" }, NOW, "download-idta",
  );
  const resolved = applySourceResolution(original, {
    sources: [{
      requested_item: "IDTA AAS Part 1 Metamodel",
      source_url: "https://example.org/idta.pdf",
      filename: "idta.pdf",
      license_class: "open-specification",
      redistributable: true,
      official: true,
    }],
    unresolved: [],
  }, "2026-08-30T00:01:00.000Z");
  assert.equal(resolved.download_id, original.download_id);
  assert.equal(resolved.status, "QUEUED");
  assert.equal(resolved.assets[0].filename, "idta.pdf");
});

test("zero legal sources blocks instead of hanging", () => {
  const original = buildInitialJob({ request: "restricted standard" }, NOW, "download-blocked");
  const blocked = applySourceResolution(original, {
    sources: [],
    unresolved: [{ requested_item: "restricted standard", reason: "No legal public full text" }],
  }, "2026-08-30T00:01:00.000Z");
  assert.equal(blocked.status, "BLOCKED");
  assert.equal(blocked.next_action, null);
});

test("resolution rejects private targets, duplicates and false redistribution claims", () => {
  const original = buildInitialJob({ request: "sample" }, NOW, "download-invalid");
  assert.throws(() => applySourceResolution(original, {
    sources: [{ source_url: "https://127.0.0.1/file.pdf", filename: "a.pdf", official: true, redistributable: true }],
  }, NOW), /private target rejected/);
  assert.throws(() => applySourceResolution(original, {
    sources: [
      { source_url: "https://example.org/a.pdf", filename: "a.pdf", official: true, redistributable: true },
      { source_url: "https://example.org/b.pdf", filename: "a.pdf", official: true, redistributable: true },
    ],
  }, NOW), /duplicate filename/);
  assert.throws(() => applySourceResolution(original, {
    sources: [{ source_url: "https://example.org/a.pdf", filename: "a.pdf", official: true, redistributable: false }],
  }, NOW), /redistributable/);
});

test("identical resolution is idempotent and conflicting resolution is rejected", () => {
  const original = buildInitialJob({ request: "sample" }, NOW, "download-idempotent");
  const input = { sources: [{ source_url: "https://example.org/a.pdf", filename: "a.pdf", official: true, redistributable: true }] };
  const first = applySourceResolution(original, input, NOW);
  assert.deepEqual(applySourceResolution(first, input, NOW), first);
  assert.throws(() => applySourceResolution(first, {
    sources: [{ source_url: "https://example.org/b.pdf", filename: "b.pdf", official: true, redistributable: true }],
  }, NOW), /resolution conflict/);
});
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/download_mcp/core.test.mjs`

Expected: FAIL because `applySourceResolution` is not exported.

- [ ] **Step 3: Implement deterministic resolution fingerprints and transitions**

```ts
function sourceFingerprint(sources: unknown[], unresolved: unknown[]): string {
  return JSON.stringify({ sources, unresolved });
}

export function applySourceResolution(job: Record<string, any>, input: Record<string, any>, now: string) {
  const rawSources = Array.isArray(input.sources) ? input.sources : [];
  const unresolved = Array.isArray(input.unresolved) ? input.unresolved : [];
  if (rawSources.length > 20) throw new Error("source limit exceeded");
  const assets = normalizeSources(rawSources);
  const fingerprint = sourceFingerprint(assets, unresolved);
  if (job.resolution_fingerprint) {
    if (job.resolution_fingerprint === fingerprint) return structuredClone(job);
    throw new Error("resolution conflict");
  }
  if (job.status !== "RESOLVING") throw new Error("job is not resolving");
  const next = structuredClone(job);
  next.assets = assets;
  next.unresolved = normalizeUnresolved(unresolved);
  next.resolution_fingerprint = fingerprint;
  next.updated_at = now;
  next.blocker = assets.length ? null : "No legal public source was resolved";
  next.status = assets.length ? "QUEUED" : "BLOCKED";
  next.current_stage = next.status;
  next.next_action = assets.length
    ? { action: "WAIT_EXECUTOR", required: false, retry_after_seconds: 300 }
    : null;
  return next;
}
```

`normalizeSources` must require `official===true`, `redistributable===true`, a safe HTTPS URL, a sanitized filename, unique canonical URL/filename, optional positive safe integer size and optional `/^[a-f0-9]{64}$/` SHA-256. It calls `buildAsset` and records `requested_item`, `license_class`, `official` and `redistributable`.

Wire `resolve_download_sources` in `callTool`: read the current row, apply the transition, persist with `updateJob(id, revision, job)`, and return the re-read job. Update MCP server instructions to tell ChatGPT to search official/legal public sources and call this tool on the same job before stopping.

- [ ] **Step 4: Run and verify GREEN**

Run: `node --test tests/download_mcp/core.test.mjs`

Expected: all initial and resolution tests PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add supabase/functions/download-mcp tests/download_mcp/core.test.mjs
git commit -m "feat: accept reviewed source resolutions"
```

---

### Task 3: Add leased queue claims and automatic verified completion

**Files:**
- Modify: `supabase/functions/download-mcp/core.ts`
- Modify: `supabase/functions/download-mcp/index.ts`
- Modify: `tests/download_mcp/core.test.mjs`

**Interfaces:**
- Consumes: optimistic `getJob`/`updateJob`, exact GitHub OIDC verifier and job shapes.
- Produces: `isClaimEligible(job, nowMs)`, `applyClaim(job, now, leaseMs)`, `applyExecutorResult(job, result, now)` and `POST /executor/claim`.

- [ ] **Step 1: Add failing lease and completion tests**

```js
import {
  applyClaim,
  applyExecutorResult,
  isClaimEligible,
} from "../../supabase/functions/download-mcp/core.ts";

test("queued and expired jobs are claimable but active leases are not", () => {
  assert.equal(isClaimEligible({ status: "QUEUED", executor: null }, Date.parse(NOW)), true);
  assert.equal(isClaimEligible({
    status: "FETCHING",
    executor: { status: "CLAIMED", claim_expires_at: "2026-08-29T23:59:00.000Z" },
  }, Date.parse(NOW)), true);
  assert.equal(isClaimEligible({
    status: "FETCHING",
    executor: { status: "CLAIMED", claim_expires_at: "2026-08-30T00:19:00.000Z" },
  }, Date.parse(NOW)), false);
});

test("claim records a twenty-minute lease", () => {
  const claimed = applyClaim({ status: "QUEUED", current_stage: "QUEUED" }, NOW, 20 * 60_000);
  assert.equal(claimed.status, "FETCHING");
  assert.equal(claimed.executor.status, "CLAIMED");
  assert.equal(claimed.executor.claim_expires_at, "2026-08-30T00:20:00.000Z");
});

test("verified all-pass executor result completes without a finalize action", () => {
  const job = {
    download_id: "download-pass",
    status: "FETCHING",
    assets: [{ asset_id: "asset-1", filename: "a.pdf", state: "PENDING" }],
    drive_refs: [], pass_files: [], failed_files: [], drive_verified: false,
  };
  const result = {
    assets: [{ asset_id: "asset-1", filename: "a.pdf", status: "PASS", bytes: 42, sha256: "a".repeat(64), drive_ref: { file_id: "drive-1", name: "a.pdf", size: 42, sha256: "a".repeat(64) } }],
    drive_refs: [{ file_id: "drive-1", name: "a.pdf", size: 42, sha256: "a".repeat(64) }],
    drive_verified: true,
  };
  const completed = applyExecutorResult(job, result, NOW);
  assert.equal(completed.status, "COMPLETED");
  assert.equal(completed.drive_verified, true);
  assert.equal(completed.next_action, null);
});

test("missing Drive evidence cannot complete", () => {
  const job = { download_id: "download-no-drive", status: "FETCHING", assets: [{ asset_id: "asset-1", filename: "a.pdf" }], drive_refs: [] };
  const next = applyExecutorResult(job, { assets: [{ asset_id: "asset-1", status: "PASS", bytes: 42, sha256: "a".repeat(64) }], drive_refs: [], drive_verified: false }, NOW);
  assert.notEqual(next.status, "COMPLETED");
});
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/download_mcp/core.test.mjs`

Expected: FAIL because the claim/result functions are absent.

- [ ] **Step 3: Implement the pure lease and completion rules**

```ts
export function isClaimEligible(job: Record<string, any>, nowMs: number): boolean {
  if (job.status === "QUEUED") return true;
  const expires = Date.parse(String(job.executor?.claim_expires_at ?? ""));
  return job.status === "FETCHING" && job.executor?.status === "CLAIMED" &&
    Number.isFinite(expires) && expires <= nowMs;
}

export function applyClaim(job: Record<string, any>, now: string, leaseMs: number) {
  const next = structuredClone(job);
  next.status = "FETCHING";
  next.current_stage = "FETCHING";
  next.next_action = null;
  next.updated_at = now;
  next.executor = {
    status: "CLAIMED",
    claimed_at: now,
    claim_expires_at: new Date(Date.parse(now) + leaseMs).toISOString(),
  };
  return next;
}
```

Move the current result-normalization logic into `applyExecutorResult`. Set `COMPLETED` in the same transition only when every asset passes, every passed file has a Drive reference, `result.drive_verified===true`, and SHA/size/file ID are non-empty. Preserve explicit `PARTIAL`, `FAILED` and `AUTH_REQUIRED` branches.

- [ ] **Step 4: Add the OIDC-only claim adapter**

In `index.ts`, add `claimNextJob()` that queries at most 20 rows ordered by `created_at.asc`, evaluates `isClaimEligible`, and calls the existing revision-guarded `updateJob`. On revision conflict it continues to the next candidate. The HTTP handler is:

```ts
if (sub === "/executor/claim" && req.method === "POST") {
  try {
    await verifyExecutor(req);
    const claim = await claimNextJob();
    return claim ? json(req, { download_id: claim.download_id }, 200) : new Response(null, { status: 204 });
  } catch (error) {
    return json(req, { error: error instanceof Error ? error.message : String(error) }, 401);
  }
}
```

Return only `download_id`; never include assets or source URLs in the claim response.

- [ ] **Step 5: Run and verify GREEN**

Run: `node --test tests/download_mcp/core.test.mjs`

Expected: all control-plane tests PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add supabase/functions/download-mcp tests/download_mcp/core.test.mjs
git commit -m "feat: claim and finalize download jobs"
```

---

### Task 4: Honor safe nested Google Drive destinations

**Files:**
- Create: `supabase/functions/download-drive/path.ts`
- Create: `supabase/functions/download-drive/index.ts`
- Create: `tests/download_drive/path.test.mjs`

**Interfaces:**
- Consumes: exact production `download-drive` v3 source, existing root-folder/OAuth/OIDC/session functions.
- Produces: `normalizeDestination(value)`, `escapeDriveQueryLiteral(value)`, `ensureDestinationFolder(root, segments)`, destination-aware session/readback.

- [ ] **Step 1: Write failing path contracts**

```js
// tests/download_drive/path.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  escapeDriveQueryLiteral,
  normalizeDestination,
} from "../../supabase/functions/download-drive/path.ts";

test("normalizes user destination below 下载", () => {
  assert.deepEqual(
    normalizeDestination("Google Drive/汽车智能制造标准研究_2026/下载插件验收_20260830/"),
    ["汽车智能制造标准研究_2026", "下载插件验收_20260830"],
  );
  assert.deepEqual(normalizeDestination("Google Drive\\下载\\A\\B"), ["A", "B"]);
});

test("rejects traversal, absolute, control, depth and overlong segments", () => {
  for (const value of [
    "../outside", "/absolute", "C:\\absolute", "A/..", "A/\u0000B",
    "1/2/3/4/5/6/7/8/9", "x".repeat(101),
  ]) assert.throws(() => normalizeDestination(value));
});

test("escapes Drive query literals", () => {
  assert.equal(escapeDriveQueryLiteral("O'Reilly\\A"), "O\\'Reilly\\\\A");
});
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/download_drive/path.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `path.ts`.

- [ ] **Step 3: Implement exact path normalization**

```ts
export function normalizeDestination(value: unknown): string[] {
  if (value == null || String(value).trim() === "") return [];
  const raw = String(value).trim();
  if (/^(?:[A-Za-z]:[\\/]|[\\/])/.test(raw)) throw new Error("absolute Drive destination rejected");
  let parts = raw.split(/[\\/]+/).map((part) => part.trim()).filter(Boolean);
  while (/^(google drive|下载)$/i.test(parts[0] ?? "")) parts = parts.slice(1);
  parts = parts.filter((part) => part !== ".");
  if (parts.some((part) => part === "..")) throw new Error("Drive destination traversal rejected");
  if (parts.some((part) => /[\u0000-\u001f\u007f]/.test(part))) throw new Error("Drive destination control character rejected");
  if (parts.some((part) => part.length > 100)) throw new Error("Drive destination segment too long");
  if (parts.length > 8) throw new Error("Drive destination depth exceeded");
  return parts;
}

export function escapeDriveQueryLiteral(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}
```

- [ ] **Step 4: Integrate nested folder creation and expected-parent verification**

Create `download-drive/index.ts` from production v3. Add:

```ts
async function ensureChildFolder(parentId: string, name: string) {
  const escaped = escapeDriveQueryLiteral(name);
  const query = `trashed = false and mimeType = '${FOLDER_MIME}' and name = '${escaped}' and '${parentId}' in parents`;
  const files = await listDriveFiles(query, "files(id,name,mimeType,parents,webViewLink,trashed)");
  if (files.length > 1) throw new Error("Multiple destination folders match the same parent/name");
  if (files[0]) return files[0];
  return createDriveFolder(parentId, name);
}

async function ensureDestinationFolder(destination: unknown) {
  let folder = await ensureRootFolder();
  for (const segment of normalizeDestination(destination)) {
    folder = await ensureChildFolder(folder.id, segment);
  }
  return folder;
}
```

`sessions(downloadId, oidc)` fetches the job first, resolves `job.destination`, and passes the leaf ID to every `createUploadSession`. Its response includes `destination_folder` and normalized `destination_segments`.

`verifyRefs(downloadId, refs)` fetches the job, resolves the same leaf, and requires every Drive metadata `parents` array to include that leaf ID. Return the leaf folder ID/path with verified refs.

- [ ] **Step 5: Run all local contracts and verify GREEN**

```powershell
node --test tests/download_drive/path.test.mjs tests/download_mcp/core.test.mjs
python -m unittest discover -s tests/download_executor -v
```

Expected: all Node and Python tests PASS.

- [ ] **Step 6: Commit Task 4**

```powershell
git add supabase/functions/download-drive tests/download_drive
git commit -m "feat: archive downloads into safe Drive paths"
```

---

### Task 5: Turn GitHub Actions into a secretless queue consumer

**Files:**
- Create: `tests/download_executor/test_queue_workflow.py`
- Modify: `.github/workflows/download-executor.yml:3-60,75-260`
- Modify: `.github/workflows/download-executor-ci.yml:6-22,34-42`
- Modify: `.github/workflows/download-plugin-staging-acceptance.yml`

**Interfaces:**
- Consumes: `POST /executor/claim`, existing OIDC/job/session/result endpoints.
- Produces: scheduled/manual queue execution while preserving descriptor-push recovery.

- [ ] **Step 1: Write a failing workflow contract**

```py
# tests/download_executor/test_queue_workflow.py
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/download-executor.yml").read_text(encoding="utf-8")

class QueueWorkflowContracts(unittest.TestCase):
    def test_schedule_and_manual_recovery_are_enabled(self):
        self.assertIn("cron: '*/5 * * * *'", WORKFLOW)
        self.assertIn("workflow_dispatch:", WORKFLOW)

    def test_non_push_run_claims_with_oidc_and_allows_empty_queue(self):
        self.assertIn("/download-mcp/executor/claim", WORKFLOW)
        self.assertIn("code=$(curl -sS -o claim.json -w '%{http_code}' -X POST", WORKFLOW)
        self.assertIn("if [ \"$code\" = '204' ]; then", WORKFLOW)
        self.assertIn("echo 'found=false' >> \"$GITHUB_OUTPUT\"", WORKFLOW)

    def test_descriptor_push_recovery_is_preserved(self):
        self.assertIn("git diff-tree --no-commit-id", WORKFLOW)
        self.assertIn("validate_descriptor", WORKFLOW)

    def test_execution_steps_are_guarded_by_found_output(self):
        self.assertGreaterEqual(WORKFLOW.count("steps.descriptor.outputs.found == 'true'"), 8)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m unittest tests.download_executor.test_queue_workflow -v
```

Expected: failures for missing schedule, manual trigger, claim endpoint and found guards.

- [ ] **Step 3: Add schedule/manual triggers and move OIDC before selection**

Set the workflow header to:

```yaml
on:
  push:
    branches: [main]
    paths:
      - '.download/jobs/**'
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch:
```

Keep checkout first, move `Request GitHub OIDC identity` second, and replace `Resolve descriptor` with event-aware selection:

```bash
set -euo pipefail
if [ "$GITHUB_EVENT_NAME" = 'push' ]; then
  path=$(git diff-tree --no-commit-id --name-only -r "$GITHUB_SHA" | grep '^\.download/jobs/.*\.json$' | head -n 1)
  test -n "$path"
  id=$(python - "$path" <<'PY'
import json, sys
from scripts.download_executor import validate_descriptor
print(validate_descriptor(json.load(open(sys.argv[1],encoding='utf-8'))))
PY
  )
else
  code=$(curl -sS -o claim.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $OIDC_TOKEN" \
    'https://ezvfqrhzucjvkwnnbjux.supabase.co/functions/v1/download-mcp/executor/claim')
  if [ "$code" = '204' ]; then
    echo 'found=false' >> "$GITHUB_OUTPUT"
    echo 'DOWNLOAD_QUEUE=EMPTY'
    exit 0
  fi
  test "$code" = '200'
  id=$(python -c 'import json; print(json.load(open("claim.json"))["download_id"])')
fi
echo 'found=true' >> "$GITHUB_OUTPUT"
echo "download_id=$id" >> "$GITHUB_OUTPUT"
echo "DOWNLOAD_ID=$id"
```

Pass `OIDC_TOKEN` from the previous step. Add `if: steps.descriptor.outputs.found == 'true'` to payload fetch, Drive sessions, preflight, browser detection/install, execute, artifact upload, Drive verify and result submit steps. Preserve all current endpoint strings and executor behavior.

- [ ] **Step 4: Update staging MCP assertions**

Change the expected tool list to include `resolve_download_sources`; direct URL status/next action becomes `QUEUED`/`WAIT_EXECUTOR`. Add a name-only case that calls `resolve_download_sources` and asserts the same job becomes `QUEUED`. Assert all six tools have `outputSchema`.

- [ ] **Step 5: Run workflow and full regression tests**

```powershell
python -m unittest discover -s tests/download_executor -v
node --test tests/download_mcp/*.test.mjs tests/download_drive/*.test.mjs
```

Expected: every Python/Node contract PASS, including existing production-routing and direct-Drive tests.

- [ ] **Step 6: Commit Task 5**

```powershell
git add .github/workflows tests/download_executor/test_queue_workflow.py
git commit -m "feat: poll download queue with GitHub OIDC"
```

---

### Task 6: Deploy and verify staging control-plane contracts

**Files:**
- Modify only if staging evidence requires a correction: files from Tasks 1-5.
- Record: `docs/ARCHIVE_WORKFLOW.md`

**Interfaces:**
- Consumes: source-controlled functions, Supabase project `ezvfqrhzucjvkwnnbjux`, staging slugs `download-mcp-staging` and `download-drive-staging`.
- Produces: staging function versions and evidence that MCP/state/policy contracts pass before production.

- [ ] **Step 1: Capture rollback sources and current versions**

Use Supabase `get_edge_function` for `download-mcp-staging`, `download-drive-staging`, `download-mcp` and `download-drive`. Save their version numbers and SHA-256 values in the execution log; do not write raw private paths/tokens to the repository.

- [ ] **Step 2: Re-run the full local gate immediately before deployment**

```powershell
python -m unittest discover -s tests/download_executor -v
node --test tests/download_mcp/*.test.mjs tests/download_drive/*.test.mjs
git diff --check
```

Expected: zero failures and clean whitespace.

- [ ] **Step 3: Deploy staging functions**

Deploy repository `download-mcp` source to `download-mcp-staging` and `download-drive` source to `download-drive-staging` with `verify_jwt=false`. Include each handler, its pure module and `_shared/memory_export_core.ts` where imported.

- [ ] **Step 4: Run staging MCP calls directly**

Against the fixed private staging path:

1. `initialize` returns MCP `2025-06-18` and server version `0.4.0-autonomous-queue`.
2. `tools/list` returns six tools with output schemas.
3. direct public PDF URL creates `QUEUED`/`WAIT_EXECUTOR`.
4. name-only input creates `RESOLVING`.
5. `resolve_download_sources` moves the same job to `QUEUED`.
6. private URL and paywall-bypass request return `isError=true` and do not increase job count.

- [ ] **Step 5: Inspect staging logs and state rows**

Query only the staging test IDs. Require consistent stage/status fields, no source query strings in logs, no 5xx, and no unexpected executor claim. If any contract fails, redeploy captured staging sources before changing another component.

- [ ] **Step 6: Document the queue operating model**

Add to `docs/ARCHIVE_WORKFLOW.md`:

```markdown
## ChatGPT plugin queue

Direct HTTPS jobs enter `QUEUED`. Name/number-only jobs remain `RESOLVING` until web Chat submits reviewed official/public sources through `resolve_download_sources`. The GitHub executor claims one queued job every five minutes using repository/ref/workflow-bound OIDC. A successful verified Drive upload completes automatically; no descriptor commit or manual finalize call is part of normal operation.

All destinations are relative to the plugin-owned Drive folder `下载`. For example, `Google Drive/A/B` is archived as `下载/A/B`.
```

- [ ] **Step 7: Commit Task 6 documentation**

```powershell
git add docs/ARCHIVE_WORKFLOW.md
git commit -m "docs: operate autonomous download queue"
```

---

### Task 7: Release to production and execute both web gates

**Files:**
- Production deploy: `supabase/functions/download-mcp/**`, `supabase/functions/download-drive/**`
- Production workflow: `.github/workflows/download-executor.yml`
- Release evidence: Supabase rows/logs, GitHub run, Drive metadata and web Chat conversations.

**Interfaces:**
- Consumes: all passing Tasks 1-6 and existing blocked IDs.
- Produces: production `download-mcp`/`download-drive`, default-branch scheduled workflow and acceptance evidence.

- [ ] **Step 1: Publish repository commits atomically**

Before updating `main`, fetch its current remote head and confirm it still equals the implementation base. Publish the local commits through the GitHub connector as one fast-forward update; never force-update. Verify the remote commit contains all function sources, tests, CI, workflow and docs.

- [ ] **Step 2: Wait for CI and inspect every failing step if present**

Require `Download Executor CI` to show all Python and Node contracts passing. A red CI run blocks Supabase production deployment.

- [ ] **Step 3: Deploy production functions with rollback versions recorded**

Deploy `download-drive` first and `download-mcp` second, both with `verify_jwt=false`. Confirm both are `ACTIVE`, the project is `ACTIVE_HEALTHY`, the plain `/mcp` path still returns 404, and the fixed private path initializes without exposing its capability.

- [ ] **Step 4: Migrate only the existing IDTA direct-URL job**

Run a revision-guarded SQL data repair for `download-d57308b96f1b42ad8a128a31a60421f2`: require current `status='FETCHING'`, `executor is null` and one existing asset; set `status/current_stage='QUEUED'`, `next_action={"action":"WAIT_EXECUTOR","required":false,"retry_after_seconds":300}`, clear blocker, preserve request/assets/destination, and increment revision. Do not change `download-e9a89e2307b6463fa4e94babedfb6db4`.

- [ ] **Step 5: Verify the direct-URL production gate without a descriptor commit**

Wait for a scheduled GitHub run—not a `.download/jobs/` commit—to claim the IDTA job. Require:

- `executor.status` advances from claim to normalized run evidence;
- PDF magic passes and downloaded size is non-zero;
- SHA-256 is 64 lowercase hex characters;
- `drive_verified=true`, one Drive file ID, exact Drive size and expected nested parent;
- final state is `COMPLETED` with `next_action=null`; and
- the Drive connector independently reads the same name, size and leaf-folder parent.

- [ ] **Step 6: Verify the standards-number production gate in a fresh web Chat**

Start a new conversation with `@下载` and request one known open standard by name/number without a URL. The conversation must:

1. call `start_download` and receive `RESOLVING`;
2. use web research to select an official/legal public direct source;
3. call `resolve_download_sources` on the same `download_id`;
4. observe `QUEUED` and later `COMPLETED`; and
5. report source URL, exact bytes, SHA-256, Drive file ID and verified destination.

If Chat stops after step 1, revise only MCP instructions/tool descriptions, add a failing wording/contract test, redeploy, and retry with a new job. Do not manually commit a descriptor.

- [ ] **Step 7: Run Work and negative regressions**

In Work, start one legal public direct-URL sample and require durable `download_id` plus eventual completion. Re-run:

- private target rejection;
- paywall/DRM bypass rejection;
- duplicate source and conflicting resolution rejection;
- invalid Drive traversal/depth rejection;
- active-lease duplicate claim rejection;
- expired-lease reclaim; and
- idempotent `get_download`/`finalize_download` on completed work.

Compare the `download_job` row count before/after rejected tests; rejected inputs must create no dirty rows.

- [ ] **Step 8: Run completion verification**

Freshly query the two gate jobs, Drive metadata, latest relevant edge logs and GitHub run. Require all relevant HTTP records to be 2xx, zero unexplained 5xx, no stuck `CLAIMED` lease and no unverified Drive reference. Run locally again:

```powershell
python -m unittest discover -s tests/download_executor -v
node --test tests/download_mcp/*.test.mjs tests/download_drive/*.test.mjs
git status --short --branch
git log --oneline -7
```

- [ ] **Step 9: Release decision**

Permit the 10-standard gate only if both single-item production gates pass without Codex intervention. If either gate fails, keep bulk release blocked, preserve the durable job evidence, and rollback only the affected function/workflow version.


