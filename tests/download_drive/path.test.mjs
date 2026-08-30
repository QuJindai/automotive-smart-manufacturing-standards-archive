import test from "node:test";
import assert from "node:assert/strict";

import {
  downloadDriveSubpath,
  downloadMcpServiceForDrive,
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
    "../outside",
    "/absolute",
    "C:\\absolute",
    "A/..",
    "A/\u0000B",
    "1/2/3/4/5/6/7/8/9",
    "x".repeat(101),
  ]) {
    assert.throws(() => normalizeDestination(value), value);
  }
});

test("escapes Drive query literals", () => {
  assert.equal(escapeDriveQueryLiteral("O'Reilly\\A"), "O\\'Reilly\\\\A");
});

test("production and staging Drive slugs resolve the same executor subpath", () => {
  assert.equal(
    downloadDriveSubpath("/functions/v1/download-drive/executor/sessions/job"),
    "/executor/sessions/job",
  );
  assert.equal(
    downloadDriveSubpath("/functions/v1/download-drive-staging/executor/sessions/job"),
    "/executor/sessions/job",
  );
});

test("staging Drive reads jobs from the staging control plane", () => {
  assert.equal(
    downloadMcpServiceForDrive("/functions/v1/download-drive/executor/sessions/job"),
    "download-mcp",
  );
  assert.equal(
    downloadMcpServiceForDrive("/functions/v1/download-drive-staging/executor/sessions/job"),
    "download-mcp-staging",
  );
});

