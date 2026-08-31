export const PRIVATE_PATH_SHA256 =
  "04a7f402eeef7364d76701445f701ef278ce2c698469848db45ffe74bcd5c162";

export function downloadMcpSubpath(pathname: string): string {
  for (const slug of ["download-mcp-staging", "download-mcp"]) {
    const marker = `/${slug}`;
    const index = pathname.indexOf(marker);
    if (index < 0) continue;
    const after = pathname.slice(index + marker.length);
    if (after === "" || after.startsWith("/")) return after || "/";
  }
  return "/";
}

export function downloadStateKind(pathname: string): string {
  return pathname.includes("/download-mcp-staging")
    ? "download_job_staging"
    : "download_job";
}

export type JsonObject = Record<string, unknown>;

export function isPlainObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function requireText(value: unknown, name: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${name} is required`);
  }
  return value.trim();
}

export function assertPolicy(request: string): void {
  if (/\b(?:bypass|circumvent|crack|破解|绕过)\b/i.test(request) &&
    /\b(?:paywall|drm|login|authentication|付费墙|登录|鉴权)\b/i.test(request)) {
    throw new Error("access-control bypass requests are not allowed");
  }
}

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return false;
  const octets = parts.map(Number);
  if (octets.some((part) => part > 255)) return false;
  return octets[0] === 0 || octets[0] === 10 || octets[0] === 127 ||
    (octets[0] === 169 && octets[1] === 254) ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168) ||
    octets[0] >= 224;
}

export function safeUrl(value: unknown): URL {
  const raw = requireText(value, "source_url");
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("invalid source URL");
  }
  if (parsed.protocol !== "https:") throw new Error("only HTTPS sources are allowed");
  if (parsed.username || parsed.password) throw new Error("embedded URL credentials rejected");
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost") || host === "::1" ||
    host.startsWith("fe80:") || host.startsWith("fc") || host.startsWith("fd") ||
    host === "metadata.google.internal" || host === "metadata.google" ||
    isPrivateIpv4(host)) {
    throw new Error("private target rejected");
  }
  return parsed;
}

export function extractUrls(request: string): string[] {
  const matches = request.match(/https:\/\/[^\s<>"'）)]+/gi) ?? [];
  return [...new Set(matches.map((value) => safeUrl(value).toString()))];
}

export function sanitizedFilename(value: string): string {
  const cleaned = value.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, "_").trim();
  if (!cleaned || cleaned === "." || cleaned === "..") return "download.bin";
  return cleaned.slice(0, 180);
}

function hostIs(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

function providerFor(url: URL) {
  const hostname = url.hostname.toLowerCase();
  const pathname = decodeURIComponent(url.pathname);
  let provider = "generic_https";
  let browserHint = false;

  if (hostIs(hostname, "arxiv.org")) {
    provider = "arxiv";
  } else if (hostIs(hostname, "huggingface.co")) {
    provider = pathname.includes("/datasets/")
      ? "huggingface_dataset"
      : "huggingface_model";
  } else if (hostIs(hostname, "modelscope.cn")) {
    provider = "modelscope";
  } else if (hostIs(hostname, "un.org") || hostIs(hostname, "unece.org")) {
    provider = "un_documents";
    browserHint = true;
  } else if (hostIs(hostname, "europa.eu")) {
    provider = "eur_lex";
    browserHint = true;
  } else if (hostIs(hostname, "dhs.gov")) {
    provider = "dhs";
    browserHint = true;
  } else if (hostIs(hostname, "transportation.gov") || hostIs(hostname, "dot.gov")) {
    provider = "us_dot";
    browserHint = true;
  } else if (hostIs(hostname, "github.com") || hostIs(hostname, "githubusercontent.com")) {
    provider = "github";
  }

  let filename = sanitizedFilename(
    pathname.split("/").filter(Boolean).at(-1) ?? "download.bin",
  );
  if (provider === "arxiv" && !filename.toLowerCase().endsWith(".pdf")) {
    filename = sanitizedFilename(`${filename}.pdf`);
  }
  const lowerName = filename.toLowerCase();
  const kind = lowerName.endsWith(".pdf")
    ? "pdf"
    : lowerName.endsWith(".gguf")
    ? "gguf"
    : lowerName.endsWith(".zip")
    ? "zip"
    : lowerName.endsWith(".safetensors")
    ? "safetensors"
    : "binary";
  const contentTypeHint = kind === "pdf"
    ? "application/pdf"
    : kind === "zip"
    ? "application/zip"
    : kind === "binary"
    ? null
    : "application/octet-stream";

  return {
    source_url: url.toString(),
    canonical_url: url.toString(),
    provider,
    filename,
    kind,
    content_type_hint: contentTypeHint,
    fallback_chain: browserHint
      ? ["native", "browser", "alternate_egress"]
      : ["native", "browser"],
    browser_hint: browserHint,
    range_hint: true,
  };
}

export function buildAsset(value: unknown, index: number) {
  const url = safeUrl(value);
  const source = providerFor(url);
  return {
    asset_id: `asset-${index + 1}`,
    ...source,
    state: "PENDING",
    fallback_index: 0,
    evidence: {
      fallback_chain: source.fallback_chain,
      browser_hint: source.browser_hint,
      range_hint: true,
    },
  };
}

export function buildInitialJob(args: JsonObject, now: string, downloadId: string) {
  const request = requireText(args.request, "request");
  assertPolicy(request);
  const assets = extractUrls(request).map((url, index) => buildAsset(url, index));
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

function normalizeUnresolved(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map((entry, index) => {
    if (!isPlainObject(entry)) throw new Error(`unresolved[${index}] must be an object`);
    return {
      requested_item: requireText(entry.requested_item, `unresolved[${index}].requested_item`),
      reason: requireText(entry.reason, `unresolved[${index}].reason`),
    };
  });
}

function optionalPositiveInteger(value: unknown, name: string): number | undefined {
  if (value == null || value === "") return undefined;
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number <= 0) throw new Error(`${name} must be a positive safe integer`);
  return number;
}

function optionalSha256(value: unknown, name: string): string | undefined {
  if (value == null || value === "") return undefined;
  const digest = String(value).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error(`${name} must be a SHA-256 hex digest`);
  return digest;
}

function normalizeSources(value: unknown) {
  if (!Array.isArray(value)) throw new Error("sources must be an array");
  if (value.length > 20) throw new Error("source limit exceeded");
  const filenames = new Set<string>();
  const urls = new Set<string>();

  return value.map((entry, index) => {
    if (!isPlainObject(entry)) throw new Error(`sources[${index}] must be an object`);
    if (entry.official !== true) throw new Error(`sources[${index}] must be official`);
    if (entry.redistributable !== true) {
      throw new Error(`sources[${index}] must be explicitly redistributable`);
    }
    const parsed = safeUrl(entry.source_url);
    const canonicalUrl = parsed.toString();
    const filename = sanitizedFilename(requireText(entry.filename, `sources[${index}].filename`));
    const filenameKey = filename.toLocaleLowerCase("en-US");
    if (urls.has(canonicalUrl)) throw new Error("duplicate source URL");
    if (filenames.has(filenameKey)) throw new Error("duplicate filename");
    urls.add(canonicalUrl);
    filenames.add(filenameKey);

    const asset = buildAsset(canonicalUrl, index);
    const expectedSize = optionalPositiveInteger(
      entry.expected_size_bytes ?? entry.size,
      `sources[${index}].expected_size_bytes`,
    );
    const expectedSha256 = optionalSha256(
      entry.expected_sha256 ?? entry.sha256,
      `sources[${index}].expected_sha256`,
    );
    return {
      ...asset,
      filename,
      canonical_url: canonicalUrl,
      requested_item: typeof entry.requested_item === "string" ? entry.requested_item.trim() : null,
      license_class: typeof entry.license_class === "string" ? entry.license_class.trim() : null,
      official: true,
      redistributable: true,
      ...(expectedSize ? { expected_size_bytes: expectedSize } : {}),
      ...(expectedSha256 ? { expected_sha256: expectedSha256 } : {}),
    };
  });
}

function sourceFingerprint(sources: unknown[], unresolved: unknown[]): string {
  return JSON.stringify({ sources, unresolved });
}

export function applySourceResolution(
  job: Record<string, any>,
  input: Record<string, any>,
  now: string,
) {
  const assets = normalizeSources(input.sources ?? []);
  const unresolved = normalizeUnresolved(input.unresolved ?? []);
  const fingerprint = sourceFingerprint(assets, unresolved);

  if (job.resolution_fingerprint) {
    if (job.resolution_fingerprint === fingerprint) return structuredClone(job);
    throw new Error("resolution conflict");
  }
  if (job.status !== "RESOLVING") throw new Error("job is not resolving");

  const next = structuredClone(job);
  next.assets = assets;
  next.unresolved = unresolved;
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

export function isClaimEligible(job: Record<string, any>, nowMs: number): boolean {
  if (job.status === "QUEUED") return true;
  const expires = Date.parse(String(job.executor?.claim_expires_at ?? ""));
  return job.status === "FETCHING" && job.executor?.status === "CLAIMED" &&
    Number.isFinite(expires) && expires <= nowMs;
}

export function applyClaim(
  job: Record<string, any>,
  now: string,
  leaseMs: number,
) {
  const nowMs = Date.parse(now);
  if (!Number.isFinite(nowMs)) throw new Error("invalid claim time");
  if (!Number.isSafeInteger(leaseMs) || leaseMs <= 0) throw new Error("invalid executor lease");
  if (!isClaimEligible(job, nowMs)) throw new Error("job is not claimable");
  const next = structuredClone(job);
  next.status = "FETCHING";
  next.current_stage = "FETCHING";
  next.next_action = null;
  next.blocker = null;
  next.updated_at = now;
  next.executor = {
    status: "CLAIMED",
    claimed_at: now,
    claim_expires_at: new Date(nowMs + leaseMs).toISOString(),
  };
  return next;
}

function mergedDriveRefs(result: Record<string, any>) {
  const values = [
    ...(Array.isArray(result.drive_refs) ? result.drive_refs : []),
    ...(Array.isArray(result.assets)
      ? result.assets.map((asset: Record<string, any>) => asset?.drive_ref).filter(Boolean)
      : []),
  ];
  const output: Record<string, any>[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (!isPlainObject(value)) continue;
    const fileId = typeof value.file_id === "string" ? value.file_id.trim() : "";
    if (!fileId || seen.has(fileId)) continue;
    seen.add(fileId);
    output.push(structuredClone(value));
  }
  return output;
}

function validPassedEvidence(value: unknown): value is Record<string, any> {
  if (!isPlainObject(value) || value.status !== "PASS") return false;
  const bytes = Number(value.bytes);
  return Number.isSafeInteger(bytes) && bytes > 0 &&
    typeof value.sha256 === "string" && /^[a-f0-9]{64}$/.test(value.sha256);
}

function validDriveRef(value: unknown): value is Record<string, any> {
  if (!isPlainObject(value)) return false;
  const size = Number(value.size);
  return typeof value.file_id === "string" && value.file_id.trim() !== "" &&
    Number.isSafeInteger(size) && size > 0 &&
    typeof value.sha256 === "string" && /^[a-f0-9]{64}$/.test(value.sha256);
}

export function applyExecutorResult(
  job: Record<string, any>,
  result: Record<string, any>,
  now: string,
) {
  const next = structuredClone(job);
  const results = Array.isArray(result.assets) ? result.assets : [];
  const byId = new Map(
    results.filter(isPlainObject).map((value) => [String(value.asset_id ?? ""), value]),
  );
  next.assets = (Array.isArray(next.assets) ? next.assets : []).map((asset: Record<string, any>) => {
    const evidence = byId.get(String(asset.asset_id ?? ""));
    const passed = validPassedEvidence(evidence);
    return {
      ...asset,
      state: passed ? "PASS" : "FAIL",
      ...(passed
        ? {
          expected_size_bytes: Number(evidence.bytes),
          expected_sha256: String(evidence.sha256),
        }
        : {}),
      evidence: {
        ...(isPlainObject(asset.evidence) ? asset.evidence : {}),
        executor: evidence ?? { error: "missing executor result" },
      },
    };
  });
  next.pass_files = next.assets.filter((asset: Record<string, any>) => asset.state === "PASS")
    .map((asset: Record<string, any>) => asset.filename);
  next.failed_files = next.assets.filter((asset: Record<string, any>) => asset.state !== "PASS")
    .map((asset: Record<string, any>) => asset.filename);
  next.drive_refs = mergedDriveRefs(result);
  next.updated_at = now;
  next.executor = {
    ...(isPlainObject(job.executor) ? job.executor : {}),
    status: "FINISHED",
    completed_at: now,
    artifact: result.artifact ?? null,
    executor_exit_code: result.executor_exit_code ?? null,
    run_id: isPlainObject(result.artifact) ? result.artifact.run_id ?? null : null,
  };

  if (result.auth_required === true) {
    next.status = "AUTH_REQUIRED";
    next.current_stage = "AUTH_REQUIRED";
    next.drive_verified = false;
    next.blocker = "Google Drive write authorization is required";
    next.next_action = { action: "AUTHORIZE_DRIVE", required: true };
    return next;
  }

  const everyAssetPassed = next.assets.length > 0 && next.failed_files.length === 0;
  const refs = next.drive_refs.filter(validDriveRef);
  const referenceByName = new Map(refs.map((ref: Record<string, any>) => [String(ref.name ?? ""), ref]));
  const everyPassHasDriveEvidence = everyAssetPassed && next.assets.every((asset: Record<string, any>) => {
    const ref = referenceByName.get(String(asset.filename ?? ""));
    return ref && Number(ref.size) === Number(asset.expected_size_bytes) &&
      ref.sha256 === asset.expected_sha256;
  });

  if (everyAssetPassed && result.drive_verified === true && everyPassHasDriveEvidence) {
    next.drive_refs = refs;
    next.drive_verified = true;
    next.status = "COMPLETED";
    next.current_stage = "COMPLETED";
    next.last_verified_stage = "COMPLETED";
    next.blocker = null;
    next.next_action = null;
    return next;
  }

  next.drive_verified = false;
  if (!everyAssetPassed) {
    next.status = next.pass_files.length > 0 ? "PARTIAL" : "FAILED";
    next.current_stage = next.status;
    next.blocker = "One or more assets failed executor verification";
    next.next_action = { action: "RETRY_DOWNLOAD", required: true };
    return next;
  }

  next.status = "ARCHIVING";
  next.current_stage = "ARCHIVING";
  next.last_verified_stage = "VERIFYING";
  next.blocker = "Verified Google Drive evidence is incomplete";
  next.next_action = {
    action: "ARCHIVE_TO_DRIVE",
    required: true,
    arguments: { download_id: next.download_id, destination: next.destination },
  };
  return next;
}

const nextActionSchema = {
  anyOf: [
    { type: "object", additionalProperties: true },
    { type: "null" },
  ],
};

export const jobOutputSchema = {
  type: "object",
  additionalProperties: true,
  properties: {
    download_id: { type: "string" },
    status: { type: "string" },
    current_stage: { type: "string" },
    drive_verified: { type: "boolean" },
    pass_files: { type: "array", items: { type: "string" } },
    failed_files: { type: "array", items: { type: "string" } },
    drive_refs: { type: "array", items: { type: "object", additionalProperties: true } },
    assets: { type: "array", items: { type: "object", additionalProperties: true } },
    unresolved: { type: "array", items: { type: "object", additionalProperties: true } },
    next_action: nextActionSchema,
    retryable: { type: "boolean" },
  },
  required: [
    "download_id",
    "status",
    "current_stage",
    "drive_verified",
    "pass_files",
    "failed_files",
    "drive_refs",
    "assets",
    "unresolved",
    "next_action",
  ],
};

const idInput = {
  type: "object",
  properties: { download_id: { type: "string" } },
  required: ["download_id"],
  additionalProperties: false,
};

export function buildToolDefinitions() {
  return [
    {
      name: "start_download",
      description: "Create a durable download job. Direct public HTTPS URLs queue automatically; names and standard numbers require source resolution.",
      inputSchema: {
        type: "object",
        properties: {
          request: { type: "string" },
          destination: { type: "string" },
          constraints: { type: "object", additionalProperties: true },
        },
        required: ["request"],
        additionalProperties: false,
      },
      outputSchema: jobOutputSchema,
    },
    {
      name: "resolve_download_sources",
      description: "Submit official, legal, publicly redistributable HTTPS sources found for an existing RESOLVING job.",
      inputSchema: {
        type: "object",
        properties: {
          download_id: { type: "string" },
          sources: {
            type: "array",
            description: "Official HTTPS files whose public redistribution is explicitly permitted.",
            items: {
              type: "object",
              properties: {
                requested_item: { type: "string", description: "Original document name or standard number." },
                source_url: { type: "string", format: "uri", description: "Direct public HTTPS download URL." },
                filename: { type: "string", description: "Safe destination filename including its extension." },
                license_class: { type: "string", description: "Short redistribution basis, license, or public-document class." },
                official: { type: "boolean", const: true, description: "Must be true; only official sources are accepted." },
                redistributable: { type: "boolean", const: true, description: "Must be true after checking public redistribution rights." },
                expected_size_bytes: { type: "integer", minimum: 1 },
                expected_sha256: { type: "string", pattern: "^[A-Fa-f0-9]{64}$" },
              },
              required: ["source_url", "filename", "official", "redistributable"],
              additionalProperties: false,
            },
            maxItems: 20,
          },
          unresolved: {
            type: "array",
            items: {
              type: "object",
              properties: {
                requested_item: { type: "string" },
                reason: { type: "string" },
              },
              required: ["requested_item", "reason"],
              additionalProperties: false,
            },
          },
        },
        required: ["download_id", "sources"],
        additionalProperties: false,
      },
      outputSchema: jobOutputSchema,
    },
    { name: "get_download", description: "Read a durable download job.", inputSchema: idInput, outputSchema: jobOutputSchema },
    {
      name: "resume_download",
      description: "Resume a job with verified host-side evidence when recovery is required.",
      inputSchema: {
        type: "object",
        properties: { download_id: { type: "string" }, result: { type: "object", additionalProperties: true } },
        required: ["download_id", "result"],
        additionalProperties: false,
      },
      outputSchema: jobOutputSchema,
    },
    { name: "retry_download", description: "Retry failed assets in a durable download job.", inputSchema: idInput, outputSchema: jobOutputSchema },
    {
      name: "finalize_download",
      description: "Idempotently confirm a completed or partially completed download job.",
      inputSchema: {
        type: "object",
        properties: { download_id: { type: "string" }, allow_partial: { type: "boolean" } },
        required: ["download_id"],
        additionalProperties: false,
      },
      outputSchema: jobOutputSchema,
    },
  ];
}

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
