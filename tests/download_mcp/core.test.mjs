import test from "node:test";
import assert from "node:assert/strict";

import {
  applyClaim,
  applyExecutorResult,
  applySourceResolution,
  buildAsset,
  buildInitialJob,
  buildToolDefinitions,
  downloadMcpSubpath,
  downloadStateKind,
  isClaimEligible,
  privatePathMatches,
} from "../../supabase/functions/download-mcp/core.ts";

const NOW = "2026-08-30T00:00:00.000Z";

test("direct HTTPS request creates a queued job without a GitHub host action", () => {
  const job = buildInitialJob(
    {
      request: "IDTA https://example.org/spec.pdf",
      destination: "Google Drive/验收",
    },
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

test("production and staging function slugs resolve the same MCP subpath", () => {
  assert.equal(
    downloadMcpSubpath("/functions/v1/download-mcp/mcp/capability"),
    "/mcp/capability",
  );
  assert.equal(
    downloadMcpSubpath("/functions/v1/download-mcp-staging/mcp/capability"),
    "/mcp/capability",
  );
});

test("staging jobs use an isolated state kind", () => {
  assert.equal(downloadStateKind("/functions/v1/download-mcp/mcp/capability"), "download_job");
  assert.equal(
    downloadStateKind("/functions/v1/download-mcp-staging/mcp/capability"),
    "download_job_staging",
  );
});

test("direct sources preserve provider, file kind, and fallback compatibility", () => {
  const arxiv = buildAsset("https://arxiv.org/pdf/1706.03762", 0);
  assert.equal(arxiv.provider, "arxiv");
  assert.equal(arxiv.filename, "1706.03762.pdf");
  assert.equal(arxiv.kind, "pdf");
  assert.equal(arxiv.content_type_hint, "application/pdf");

  const model = buildAsset(
    "https://huggingface.co/openai/example/resolve/main/model.safetensors",
    1,
  );
  assert.equal(model.provider, "huggingface_model");
  assert.equal(model.kind, "safetensors");

  const dataset = buildAsset(
    "https://huggingface.co/datasets/openai/example/resolve/main/archive.zip",
    2,
  );
  assert.equal(dataset.provider, "huggingface_dataset");
  assert.equal(dataset.kind, "zip");

  const officialDocument = buildAsset(
    "https://unece.org/sites/default/files/2024-01/sample.pdf",
    3,
  );
  assert.equal(officialDocument.provider, "un_documents");
  assert.equal(officialDocument.evidence.browser_hint, true);
  assert.deepEqual(officialDocument.evidence.fallback_chain, [
    "native",
    "browser",
    "alternate_egress",
  ]);

  const release = buildAsset(
    "https://github.com/example/project/releases/download/v1/archive.zip",
    4,
  );
  assert.equal(release.provider, "github");
  assert.equal(release.kind, "zip");
});

test("official public resolution queues the same job", () => {
  const original = buildInitialJob(
    { request: "IDTA AAS Part 1 Metamodel" },
    NOW,
    "download-idta",
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
  const original = buildInitialJob(
    { request: "restricted standard" },
    NOW,
    "download-blocked",
  );
  const blocked = applySourceResolution(original, {
    sources: [],
    unresolved: [{
      requested_item: "restricted standard",
      reason: "No legal public full text",
    }],
  }, "2026-08-30T00:01:00.000Z");

  assert.equal(blocked.status, "BLOCKED");
  assert.equal(blocked.next_action, null);
});

test("resolution rejects private targets, duplicates and false redistribution claims", () => {
  const original = buildInitialJob({ request: "sample" }, NOW, "download-invalid");

  assert.throws(() => applySourceResolution(original, {
    sources: [{
      source_url: "https://127.0.0.1/file.pdf",
      filename: "a.pdf",
      official: true,
      redistributable: true,
    }],
  }, NOW), /private target rejected/);

  assert.throws(() => applySourceResolution(original, {
    sources: [
      {
        source_url: "https://example.org/a.pdf",
        filename: "a.pdf",
        official: true,
        redistributable: true,
      },
      {
        source_url: "https://example.org/b.pdf",
        filename: "a.pdf",
        official: true,
        redistributable: true,
      },
    ],
  }, NOW), /duplicate filename/);

  assert.throws(() => applySourceResolution(original, {
    sources: [{
      source_url: "https://example.org/a.pdf",
      filename: "a.pdf",
      official: true,
      redistributable: false,
    }],
  }, NOW), /redistributable/);
});

test("identical resolution is idempotent and conflicting resolution is rejected", () => {
  const original = buildInitialJob(
    { request: "sample" },
    NOW,
    "download-idempotent",
  );
  const input = {
    sources: [{
      source_url: "https://example.org/a.pdf",
      filename: "a.pdf",
      official: true,
      redistributable: true,
    }],
  };
  const first = applySourceResolution(original, input, NOW);

  assert.deepEqual(applySourceResolution(first, input, NOW), first);
  assert.throws(() => applySourceResolution(first, {
    sources: [{
      source_url: "https://example.org/b.pdf",
      filename: "b.pdf",
      official: true,
      redistributable: true,
    }],
  }, NOW), /resolution conflict/);
});

test("queued and expired jobs are claimable but active leases are not", () => {
  assert.equal(isClaimEligible({ status: "QUEUED", executor: null }, Date.parse(NOW)), true);
  assert.equal(isClaimEligible({
    status: "FETCHING",
    executor: {
      status: "CLAIMED",
      claim_expires_at: "2026-08-29T23:59:00.000Z",
    },
  }, Date.parse(NOW)), true);
  assert.equal(isClaimEligible({
    status: "FETCHING",
    executor: {
      status: "CLAIMED",
      claim_expires_at: "2026-08-30T00:19:00.000Z",
    },
  }, Date.parse(NOW)), false);
});

test("claim records a twenty-minute lease", () => {
  const claimed = applyClaim(
    { status: "QUEUED", current_stage: "QUEUED" },
    NOW,
    20 * 60_000,
  );

  assert.equal(claimed.status, "FETCHING");
  assert.equal(claimed.executor.status, "CLAIMED");
  assert.equal(claimed.executor.claim_expires_at, "2026-08-30T00:20:00.000Z");
});

test("verified all-pass executor result completes without a finalize action", () => {
  const job = {
    download_id: "download-pass",
    status: "FETCHING",
    assets: [{ asset_id: "asset-1", filename: "a.pdf", state: "PENDING" }],
    drive_refs: [],
    pass_files: [],
    failed_files: [],
    drive_verified: false,
  };
  const result = {
    assets: [{
      asset_id: "asset-1",
      filename: "a.pdf",
      status: "PASS",
      bytes: 42,
      sha256: "a".repeat(64),
      drive_ref: {
        file_id: "drive-1",
        name: "a.pdf",
        size: 42,
        sha256: "a".repeat(64),
      },
    }],
    drive_refs: [{
      file_id: "drive-1",
      name: "a.pdf",
      size: 42,
      sha256: "a".repeat(64),
    }],
    drive_verified: true,
  };
  const completed = applyExecutorResult(job, result, NOW);

  assert.equal(completed.status, "COMPLETED");
  assert.equal(completed.drive_verified, true);
  assert.equal(completed.next_action, null);
});

test("missing Drive evidence cannot complete", () => {
  const job = {
    download_id: "download-no-drive",
    status: "FETCHING",
    assets: [{ asset_id: "asset-1", filename: "a.pdf" }],
    drive_refs: [],
  };
  const next = applyExecutorResult(job, {
    assets: [{
      asset_id: "asset-1",
      status: "PASS",
      bytes: 42,
      sha256: "a".repeat(64),
    }],
    drive_refs: [],
    drive_verified: false,
  }, NOW);

  assert.notEqual(next.status, "COMPLETED");
});
