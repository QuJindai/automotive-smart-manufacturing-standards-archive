import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";
import {
  applyClaim,
  applyExecutorResult,
  applySourceResolution,
  buildInitialJob,
  buildToolDefinitions,
  downloadMcpSubpath,
  downloadStateKind,
  isClaimEligible,
  privatePathMatches,
  requireText,
} from "./core.ts";
import {
  hydrateSensitiveAssets,
  redactJob,
  stripSuccessfulSecrets,
} from "../_shared/memory_export_core.ts";

const BASE = (Deno.env.get("SUPABASE_URL") ?? "").replace(/\/$/, "");
const KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const CONFIG_ENCRYPTION_KEY = Deno.env.get("CONFIG_ENCRYPTION_KEY") ?? "";
if (!BASE || !KEY) throw new Error("Supabase service configuration is required");

const STATE_OWNER = "00000000-0000-4000-8000-000000000091";
const EXECUTOR_REPO = "QuJindai/automotive-smart-manufacturing-standards-archive";
const ISSUER = "https://token.actions.githubusercontent.com";
const JWKS = createRemoteJWKSet(new URL(`${ISSUER}/.well-known/jwks`));
const SMALL_LIMIT = 100 * 1024 * 1024;
const MCP_PROTOCOL = "2025-06-18";
const SERVER_VERSION = "0.4.1-queue-drain-schema";
const EXECUTOR_LEASE_MS = 20 * 60_000;

const securitySchemes = [{ type: "noauth" }];
const toolBase = { _meta: { securitySchemes }, securitySchemes };
const toolMetadata: Record<string, Record<string, unknown>> = {
  start_download: {
    title: "开始下载",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  },
  resolve_download_sources: {
    title: "提交下载源",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  get_download: {
    title: "查询下载",
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  resume_download: {
    title: "继续下载",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  retry_download: {
    title: "重试失败项",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  },
  finalize_download: {
    title: "完成下载",
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
};
const tools = buildToolDefinitions().map((tool) => ({
  ...toolBase,
  ...tool,
  ...(toolMetadata[tool.name] ?? {}),
}));

const allowedOrigins = new Set(["https://chatgpt.com", "https://platform.openai.com"]);

function originHeaders(req: Request) {
  const origin = req.headers.get("origin");
  const result: Record<string, string> = {
    "access-control-allow-headers": "content-type, accept, mcp-protocol-version, mcp-session-id",
    "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
    "access-control-expose-headers": "mcp-protocol-version, mcp-session-id",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "vary": "Origin",
  };
  if (origin && allowedOrigins.has(origin)) result["access-control-allow-origin"] = origin;
  return result;
}

function json(req: Request, value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      ...originHeaders(req),
      "content-type": "application/json; charset=utf-8",
      "mcp-protocol-version": MCP_PROTOCOL,
    },
  });
}

function ok(req: Request, id: unknown, value: unknown) {
  return json(req, { jsonrpc: "2.0", id: id ?? null, result: value });
}

function toolResult(value: unknown, isError = false) {
  return {
    content: [{ type: "text", text: JSON.stringify(value, null, 2) }],
    structuredContent: value,
    isError,
  };
}

function headers(prefer?: string) {
  return {
    apikey: KEY,
    authorization: `Bearer ${KEY}`,
    "content-type": "application/json",
    accept: "application/json",
    ...(prefer ? { prefer } : {}),
  };
}

async function createJob(job: Record<string, unknown>, stateKind: string) {
  const response = await fetch(`${BASE}/rest/v1/iaos_mcp_state`, {
    method: "POST",
    headers: headers("return=minimal"),
    body: JSON.stringify({
      owner_id: STATE_OWNER,
      kind: stateKind,
      record_id: job.download_id,
      payload: job,
    }),
  });
  if (!response.ok) throw new Error(`state create failed ${response.status}`);
}

async function getJob(id: string, stateKind: string) {
  const query = new URLSearchParams({
    owner_id: `eq.${STATE_OWNER}`,
    kind: `eq.${stateKind}`,
    record_id: `eq.${id}`,
    select: "payload,revision",
  });
  const response = await fetch(`${BASE}/rest/v1/iaos_mcp_state?${query}`, { headers: headers() });
  if (!response.ok) throw new Error(`state read failed ${response.status}`);
  const rows = await response.json();
  if (!rows?.[0]) throw new Error("download not found");
  return rows[0];
}

async function updateJob(id: string, revision: number, payload: Record<string, unknown>, stateKind: string) {
  const query = new URLSearchParams({
    owner_id: `eq.${STATE_OWNER}`,
    kind: `eq.${stateKind}`,
    record_id: `eq.${id}`,
    revision: `eq.${revision}`,
    select: "payload,revision",
  });
  const response = await fetch(`${BASE}/rest/v1/iaos_mcp_state?${query}`, {
    method: "PATCH",
    headers: headers("return=representation"),
    body: JSON.stringify({ payload, revision: revision + 1, updated_at: new Date().toISOString() }),
  });
  if (!response.ok) throw new Error(`state update failed ${response.status}`);
  const rows = await response.json();
  if (!rows?.[0]) throw new Error("revision conflict");
  return rows[0];
}

async function claimNextJob(stateKind: string) {
  const query = new URLSearchParams({
    owner_id: `eq.${STATE_OWNER}`,
    kind: `eq.${stateKind}`,
    "payload->>status": "in.(QUEUED,FETCHING)",
    select: "payload,revision,created_at",
    order: "created_at.asc",
    limit: "20",
  });
  const response = await fetch(`${BASE}/rest/v1/iaos_mcp_state?${query}`, { headers: headers() });
  if (!response.ok) throw new Error(`queue read failed ${response.status}`);
  const rows = await response.json();
  const now = new Date();
  for (const row of Array.isArray(rows) ? rows : []) {
    const job = row?.payload;
    if (!job || !isClaimEligible(job, now.getTime())) continue;
    try {
      const claimed = applyClaim(job, now.toISOString(), EXECUTOR_LEASE_MS);
      await updateJob(String(job.download_id), Number(row.revision), claimed, stateKind);
      return claimed;
    } catch (error) {
      if (error instanceof Error && error.message === "revision conflict") continue;
      throw error;
    }
  }
  return null;
}

async function start(args: Record<string, unknown>, stateKind: string) {
  const id = `download-${crypto.randomUUID().replaceAll("-", "")}`;
  const job = buildInitialJob(args, new Date().toISOString(), id);
  await createJob(job, stateKind);
  return job;
}

async function resolveSources(args: Record<string, unknown>, stateKind: string) {
  const id = requireText(args.download_id, "download_id");
  const row = await getJob(id, stateKind);
  const job = applySourceResolution(row.payload, args, new Date().toISOString());
  await updateJob(id, row.revision, job, stateKind);
  return (await getJob(id, stateKind)).payload;
}

function mergeRefs(left: unknown, right: unknown) {
  const output: unknown[] = [];
  const seen = new Set<string>();
  const values = [
    ...(Array.isArray(left) ? left : []),
    ...(Array.isArray(right) ? right : []),
  ];
  for (const value of values) {
    const item = value as Record<string, unknown>;
    const id = String(item?.file_id ?? item?.id ?? "");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    output.push(value);
  }
  return output;
}

async function resume(args: Record<string, unknown>, stateKind: string) {
  const id = requireText(args.download_id, "download_id");
  const row = await getJob(id, stateKind);
  const result = args.result && typeof args.result === "object" && !Array.isArray(args.result)
    ? args.result as Record<string, unknown>
    : {};
  const type = requireText(result.type, "result.type");
  const job = structuredClone(row.payload);
  if (type === "drive_archive_result") {
    if (!Array.isArray(result.drive_refs) || result.drive_refs.length === 0) {
      throw new Error("drive_archive_result requires drive_refs[]");
    }
    job.drive_refs = mergeRefs(job.drive_refs, result.drive_refs);
    job.current_stage = "DRIVE_VERIFYING";
    job.last_verified_stage = "ARCHIVING";
    job.status = "DRIVE_VERIFYING";
    job.next_action = {
      action: "VERIFY_DRIVE",
      capability: "drive.verify",
      required: true,
      arguments: { drive_refs: job.drive_refs },
    };
  } else if (type === "drive_verify_result") {
    if (result.verified !== true) throw new Error("Drive verification did not pass");
    if (!Array.isArray(job.drive_refs) || job.drive_refs.length === 0) throw new Error("Drive refs missing");
    job.drive_verified = true;
    job.current_stage = "DRIVE_VERIFYING";
    job.last_verified_stage = "DRIVE_VERIFYING";
    job.status = "DRIVE_VERIFYING";
    job.next_action = { action: "FINALIZE", capability: "download.finalize", required: true };
  } else {
    throw new Error(`unsupported resume result type: ${type}`);
  }
  job.updated_at = new Date().toISOString();
  await updateJob(id, row.revision, job, stateKind);
  return (await getJob(id, stateKind)).payload;
}

async function retry(id: string, stateKind: string) {
  const row = await getJob(id, stateKind);
  const job = structuredClone(row.payload);
  const failed = new Set(job.failed_files ?? []);
  job.assets = (job.assets ?? []).map((asset: Record<string, unknown>) =>
    failed.has(asset.filename) || asset.state === "FAIL"
      ? { ...asset, state: "PENDING", fallback_index: Number(asset.fallback_index ?? 0) + 1 }
      : asset
  );
  job.failed_files = job.assets.filter((asset: Record<string, unknown>) => asset.state === "PENDING")
    .map((asset: Record<string, unknown>) => asset.filename);
  job.current_stage = "QUEUED";
  job.status = "QUEUED";
  job.next_action = { action: "WAIT_EXECUTOR", required: false, retry_after_seconds: 300 };
  job.executor = null;
  job.updated_at = new Date().toISOString();
  await updateJob(id, row.revision, job, stateKind);
  return (await getJob(id, stateKind)).payload;
}

async function finalize(id: string, allowPartial = false, stateKind: string) {
  const row = await getJob(id, stateKind);
  const job = structuredClone(row.payload);
  if (job.status === "COMPLETED") return job;
  if (!job.drive_verified || !Array.isArray(job.drive_refs) || job.drive_refs.length === 0) {
    throw new Error("finalize requires verified Google Drive persistence");
  }
  if ((job.failed_files ?? []).length > 0) {
    if (!allowPartial) throw new Error(`download has ${job.failed_files.length} failed files`);
    job.status = "PARTIAL";
    job.next_action = null;
  } else {
    job.current_stage = "COMPLETED";
    job.last_verified_stage = "COMPLETED";
    job.status = "COMPLETED";
    job.next_action = null;
    job.blocker = null;
  }
  job.updated_at = new Date().toISOString();
  await updateJob(id, row.revision, job, stateKind);
  return (await getJob(id, stateKind)).payload;
}

async function callTool(name: string, args: Record<string, unknown>, stateKind: string) {
  let result: unknown;
  if (name === "start_download") result = await start(args, stateKind);
  else if (name === "resolve_download_sources") result = await resolveSources(args, stateKind);
  else if (name === "get_download") result = (await getJob(requireText(args.download_id, "download_id"), stateKind)).payload;
  else if (name === "resume_download") result = await resume(args, stateKind);
  else if (name === "retry_download") result = await retry(requireText(args.download_id, "download_id"), stateKind);
  else if (name === "finalize_download") {
    result = await finalize(requireText(args.download_id, "download_id"), args.allow_partial === true, stateKind);
  } else throw new Error("unknown tool");
  return redactJob(result);
}

async function verifyExecutor(req: Request) {
  const raw = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "").trim();
  if (!raw) throw new Error("missing executor OIDC token");
  const { payload } = await jwtVerify(raw, JWKS, { issuer: ISSUER, audience: "download-mcp" });
  const repository = String(payload.repository ?? "");
  const ref = String(payload.ref ?? "");
  const workflowRef = String(payload.workflow_ref ?? "");
  if (repository !== EXECUTOR_REPO) throw new Error("executor repository not allowed");
  if (ref !== "refs/heads/main") throw new Error("executor ref not allowed");
  if (!workflowRef.includes(".github/workflows/download-executor.yml@refs/heads/main")) {
    throw new Error("executor workflow not allowed");
  }
  return payload;
}

async function executorJob(id: string, stateKind: string) {
  const { payload } = await getJob(id, stateKind);
  return {
    download_id: id,
    assets: await hydrateSensitiveAssets(payload.assets, CONFIG_ENCRYPTION_KEY),
    destination: payload.destination,
    small_limit_bytes: SMALL_LIMIT,
    upload_sessions: {},
    evidence_required: true,
  };
}

async function executorResult(id: string, result: Record<string, unknown>, stateKind: string) {
  const row = await getJob(id, stateKind);
  const results = Array.isArray(result.assets) ? result.assets : [];
  const inputJob = {
    ...row.payload,
    assets: stripSuccessfulSecrets(row.payload.assets ?? [], results),
  };
  const job = applyExecutorResult(inputJob, result, new Date().toISOString());
  await updateJob(id, row.revision, job, stateKind);
  return redactJob((await getJob(id, stateKind)).payload);
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const sub = downloadMcpSubpath(url.pathname);
  const stateKind = downloadStateKind(url.pathname);

  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: originHeaders(req) });
  if (sub === "/health" && req.method === "GET") {
    return json(req, { status: "ok", service: "下载", version: SERVER_VERSION, access: "fixed-private-path" });
  }

  if (sub === "/executor/claim" && req.method === "POST") {
    try {
      await verifyExecutor(req);
      const claim = await claimNextJob(stateKind);
      return claim
        ? json(req, { download_id: claim.download_id })
        : new Response(null, { status: 204, headers: originHeaders(req) });
    } catch (error) {
      return json(req, { error: error instanceof Error ? error.message : String(error) }, 401);
    }
  }

  const jobMatch = /^\/executor\/job\/([^/]+)$/.exec(sub);
  if (jobMatch && req.method === "GET") {
    try {
      await verifyExecutor(req);
      return json(req, await executorJob(decodeURIComponent(jobMatch[1]), stateKind));
    } catch (error) {
      return json(req, { error: error instanceof Error ? error.message : String(error) }, 401);
    }
  }

  const resultMatch = /^\/executor\/result\/([^/]+)$/.exec(sub);
  if (resultMatch && req.method === "POST") {
    try {
      await verifyExecutor(req);
      return json(
        req,
        await executorResult(decodeURIComponent(resultMatch[1]), await req.json(), stateKind),
      );
    } catch (error) {
      return json(req, { error: error instanceof Error ? error.message : String(error) }, 401);
    }
  }

  if (!(await privatePathMatches(sub))) return json(req, { error: "not_found" }, 404);
  if (req.method !== "POST") return json(req, { error: "method_not_allowed" }, 405);

  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json(req, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400);
  }
  const id = payload?.id ?? null;
  if (payload?.jsonrpc !== "2.0" || typeof payload?.method !== "string") {
    return json(req, { jsonrpc: "2.0", id, error: { code: -32600, message: "Invalid Request" } });
  }
  if (payload.method === "initialize") {
    return ok(req, id, {
      protocolVersion: MCP_PROTOCOL,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "下载", version: SERVER_VERSION },
      instructions: "For a name or standard number without a URL, search the web for official, legal, publicly redistributable sources and call resolve_download_sources on the same download_id. Direct HTTPS jobs queue automatically. Report completion only after verified Google Drive persistence; never request a GitHub descriptor commit.",
    });
  }
  if (payload.method === "ping") return ok(req, id, {});
  if (payload.method === "tools/list") return ok(req, id, { tools });
  if (payload.method !== "tools/call") {
    return json(req, { jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
  }
  const params = payload.params as Record<string, unknown> | undefined;
  const name = params?.name;
  const args = params?.arguments;
  if (typeof name !== "string" || !tools.some((tool) => tool.name === name) ||
    !args || typeof args !== "object" || Array.isArray(args)) {
    return json(req, { jsonrpc: "2.0", id, error: { code: -32602, message: "Invalid params" } });
  }
  try {
    return ok(req, id, toolResult(await callTool(name, args as Record<string, unknown>, stateKind)));
  } catch (error) {
    return ok(req, id, toolResult({
      error: {
        code: "DOWNLOAD_ERROR",
        message: error instanceof Error ? error.message : String(error),
        retryable: false,
      },
    }, true));
  }
});

