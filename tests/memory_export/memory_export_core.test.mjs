import test from "node:test";
import assert from "node:assert/strict";
import * as memoryExportCore from "../../supabase/functions/_shared/memory_export_core.ts";

import {
  buildMemoryExportJob,
  extractExportCandidate,
  hasRequiredScopes,
  hydrateSensitiveAssets,
  makeSensitiveAsset,
  redactJob,
  selectLatestExportCandidate,
  stripSuccessfulSecrets,
} from "../../supabase/functions/_shared/memory_export_core.ts";

const signedUrl = "https://chatgpt.com/backend-api/estuary/content?id=file-abc&ts=1788000000&sig=top-secret";
const encryptionKey = "test-only-encryption-key-with-more-than-32-characters";

test("keeps the OAuth state valid for a full hour", () => {
  assert.equal(memoryExportCore.OAUTH_STATE_TTL_MS, 60 * 60 * 1000);
});

function b64url(value) {
  return Buffer.from(value, "utf8").toString("base64url");
}

function gmailMessage({
  id = "msg-new",
  date = "1788000000000",
  from = "OpenAI <noreply@tm.openai.com>",
  subject = "ChatGPT - 你的数据导出已准备就绪",
  html = `<a href="${signedUrl.replaceAll("&", "&amp;")}">下载数据导出</a>`,
} = {}) {
  return {
    id,
    internalDate: date,
    payload: {
      mimeType: "multipart/alternative",
      headers: [
        { name: "From", value: from },
        { name: "Subject", value: subject },
      ],
      parts: [
        { mimeType: "text/plain", body: { data: b64url("Your ChatGPT export is ready.") } },
        { mimeType: "text/html", body: { data: b64url(html) } },
      ],
    },
  };
}

test("extracts only the signed ChatGPT export URL from the expected OpenAI sender", () => {
  const candidate = extractExportCandidate(gmailMessage());
  assert.equal(candidate.messageId, "msg-new");
  assert.equal(candidate.receivedAtMs, 1788000000000);
  assert.equal(candidate.url, signedUrl);
  assert.match(candidate.filename, /^ChatGPT-memory-export-\d{4}-\d{2}-\d{2}\.zip$/);
});

test("rejects lookalike senders and non-estuary URLs", () => {
  assert.throws(
    () => extractExportCandidate(gmailMessage({ from: "OpenAI <noreply@tm.openai.com.evil.test>" })),
    /sender/i,
  );
  assert.throws(
    () => extractExportCandidate(gmailMessage({ html: '<a href="https://chatgpt.com/">download</a>' })),
    /export link/i,
  );
});

test("requires both gmail.readonly and drive.file scopes", () => {
  const scopes = "openid email https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/drive.file";
  assert.equal(hasRequiredScopes(scopes), true);
  assert.equal(hasRequiredScopes("openid email https://www.googleapis.com/auth/drive.file"), false);
});

test("selects the newest valid OpenAI export message and builds a URL-free job", async () => {
  const old = gmailMessage({ id: "msg-old", date: "1787000000000" });
  const newest = gmailMessage({ id: "msg-newest", date: "1788000000000" });
  const lookalike = gmailMessage({ id: "msg-lookalike", date: "1789000000000", from: "OpenAI <attacker@example.test>" });

  const candidate = selectLatestExportCandidate([old, lookalike, newest]);
  assert.equal(candidate.messageId, "msg-newest");

  const job = await buildMemoryExportJob({
    candidate,
    encryptionKey,
    downloadId: "download-memory-test",
    now: "2026-08-29T10:00:00.000Z",
  });
  const stored = JSON.stringify(job);
  assert.equal(stored.includes(signedUrl), false);
  assert.equal(job.destination, "Google Drive/Memory");
  assert.equal(job.source.gmail_message_id, "msg-newest");
  assert.equal(job.assets[0].sensitive_source, true);
  assert.equal(job.next_action.arguments.path, ".download/jobs/download-memory-test.json");
});

test("stores the signed URL only as ciphertext and hydrates it only for the executor", async () => {
  const asset = await makeSensitiveAsset({
    url: signedUrl,
    filename: "ChatGPT-memory-export-2026-08-29.zip",
    encryptionKey,
  });

  const stored = JSON.stringify(asset);
  assert.equal(stored.includes(signedUrl), false);
  assert.equal("source_url" in asset, false);
  assert.ok(asset.source_url_encrypted?.iv);
  assert.ok(asset.source_url_encrypted?.ciphertext);

  const hydrated = await hydrateSensitiveAssets([asset], encryptionKey);
  assert.equal(hydrated[0].source_url, signedUrl);
  assert.equal(hydrated[0].canonical_url, signedUrl);
  assert.equal("source_url_encrypted" in hydrated[0], false);
  assert.equal("canonical_url_encrypted" in hydrated[0], false);
});

test("public job output removes ciphertext and any sensitive URL fields", async () => {
  const asset = await makeSensitiveAsset({
    url: signedUrl,
    filename: "ChatGPT-memory-export-2026-08-29.zip",
    encryptionKey,
  });
  const safe = redactJob({ download_id: "download-memory-1", request: "latest export", assets: [asset] });
  const serialized = JSON.stringify(safe);
  assert.equal(serialized.includes("ciphertext"), false);
  assert.equal(serialized.includes("top-secret"), false);
  assert.equal(safe.assets[0].sensitive_source, true);
});

test("successful executor results erase encrypted URLs while failed results remain retryable", async () => {
  const passed = await makeSensitiveAsset({ url: signedUrl, filename: "passed.zip", encryptionKey });
  const failed = await makeSensitiveAsset({ url: signedUrl, filename: "failed.zip", encryptionKey });
  passed.asset_id = "asset-pass";
  failed.asset_id = "asset-fail";

  const updated = stripSuccessfulSecrets(
    [passed, failed],
    [
      { asset_id: "asset-pass", status: "PASS" },
      { asset_id: "asset-fail", status: "FAIL" },
    ],
  );

  assert.equal("source_url_encrypted" in updated[0], false);
  assert.equal("canonical_url_encrypted" in updated[0], false);
  assert.ok(updated[1].source_url_encrypted?.ciphertext);
});

test("ordinary public download jobs preserve their existing URL fields", async () => {
  const publicAsset = {
    asset_id: "asset-public",
    source_url: "https://arxiv.org/pdf/1706.03762",
    canonical_url: "https://arxiv.org/pdf/1706.03762",
    state: "PENDING",
  };
  const hydrated = await hydrateSensitiveAssets([publicAsset], "unused-for-public-assets");
  const visible = redactJob({ assets: hydrated });
  const updated = stripSuccessfulSecrets(hydrated, [{ asset_id: "asset-public", status: "PASS" }]);

  assert.deepEqual(hydrated[0], publicAsset);
  assert.deepEqual(visible.assets[0], publicAsset);
  assert.deepEqual(updated[0], publicAsset);
});
