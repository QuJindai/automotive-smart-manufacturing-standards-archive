export const GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly";
export const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";
export const OAUTH_STATE_TTL_MS = 60 * 60 * 1000;

export type EncryptedBlob = { iv: string; ciphertext: string };

type GmailHeader = { name?: string; value?: string };
type GmailPart = {
  mimeType?: string;
  headers?: GmailHeader[];
  body?: { data?: string };
  parts?: GmailPart[];
};
type GmailMessage = { id?: string; internalDate?: string; payload?: GmailPart };

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const EXPECTED_SENDER = "noreply@tm.openai.com";
const EXPORT_PATH = "/backend-api/estuary/content";

function bytesToBase64(bytes: Uint8Array): string {
  let raw = "";
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw);
}

function base64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const raw = atob(value);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let index = 0; index < raw.length; index += 1) out[index] = raw.charCodeAt(index);
  return out;
}

function decodeBase64Url(value: string): string {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4 || 4)) % 4);
  return decoder.decode(base64ToBytes(padded));
}

function headerValue(part: GmailPart | undefined, name: string): string {
  const header = part?.headers?.find((item) => item.name?.toLowerCase() === name.toLowerCase());
  return String(header?.value ?? "").trim();
}

function senderAddress(value: string): string {
  const bracketed = /<([^<>]+)>/.exec(value)?.[1];
  return String(bracketed ?? value).trim().toLowerCase();
}

function collectBodies(part: GmailPart | undefined, output: string[] = []): string[] {
  if (!part) return output;
  if (typeof part.body?.data === "string" && (!part.mimeType || part.mimeType.startsWith("text/"))) {
    output.push(decodeBase64Url(part.body.data));
  }
  for (const child of part.parts ?? []) collectBodies(child, output);
  return output;
}

function decodeHtmlEntities(value: string): string {
  return value
    .replaceAll(/&amp;/gi, "&")
    .replaceAll(/&#0*38;/gi, "&")
    .replaceAll(/&#x0*26;/gi, "&")
    .replaceAll(/&quot;/gi, '"')
    .replaceAll(/&#0*39;/gi, "'");
}

function validateExportUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(decodeHtmlEntities(raw));
  } catch {
    throw new Error("OpenAI export link is invalid");
  }
  if (url.protocol !== "https:" || url.hostname !== "chatgpt.com" || url.pathname !== EXPORT_PATH) {
    throw new Error("OpenAI export link is not an allowed ChatGPT Estuary URL");
  }
  if (!url.searchParams.get("id") || !url.searchParams.get("sig")) {
    throw new Error("OpenAI export link is missing its signed parameters");
  }
  return url.toString();
}

function findExportUrl(body: string): string {
  const decoded = decodeHtmlEntities(body);
  const candidates = decoded.match(/https:\/\/chatgpt\.com\/backend-api\/estuary\/content\?[^\s<>"']+/gi) ?? [];
  for (const candidate of candidates) {
    try {
      return validateExportUrl(candidate);
    } catch {
      // Keep looking in case a message contains both a stale lookalike and the signed link.
    }
  }
  throw new Error("OpenAI export link was not found in the message");
}

function exportFilename(receivedAtMs: number): string {
  const date = new Date(receivedAtMs);
  if (!Number.isFinite(date.valueOf())) throw new Error("Gmail message date is invalid");
  return `ChatGPT-memory-export-${date.toISOString().slice(0, 10)}.zip`;
}

export function extractExportCandidate(message: GmailMessage) {
  const from = headerValue(message.payload, "from");
  if (senderAddress(from) !== EXPECTED_SENDER) throw new Error("OpenAI export sender does not match");

  const subject = headerValue(message.payload, "subject");
  if (!/(?:data\s+export.*ready|数据导出.*(?:准备就绪|已就绪))/i.test(subject)) {
    throw new Error("Gmail subject is not an OpenAI data export notice");
  }

  const receivedAtMs = Number(message.internalDate);
  if (!Number.isSafeInteger(receivedAtMs) || receivedAtMs <= 0) throw new Error("Gmail message date is invalid");
  const url = findExportUrl(collectBodies(message.payload).join("\n"));

  return {
    messageId: String(message.id ?? ""),
    receivedAtMs,
    subject,
    url,
    filename: exportFilename(receivedAtMs),
  };
}

export function selectLatestExportCandidate(messages: GmailMessage[]) {
  const candidates = [];
  for (const message of Array.isArray(messages) ? messages : []) {
    try {
      candidates.push(extractExportCandidate(message));
    } catch {
      // Gmail search is intentionally broad; only validated OpenAI export notices survive.
    }
  }
  candidates.sort((left, right) => right.receivedAtMs - left.receivedAtMs);
  if (!candidates[0]) throw new Error("No valid OpenAI ChatGPT data export email was found");
  return candidates[0];
}

export function hasRequiredScopes(scope: string | undefined): boolean {
  const scopes = new Set(String(scope ?? "").split(/\s+/).filter(Boolean));
  return scopes.has(GMAIL_READONLY_SCOPE) && scopes.has(DRIVE_FILE_SCOPE);
}

async function cryptoKey(encryptionKey: string, usages: KeyUsage[]) {
  if (encryptionKey.length < 32) throw new Error("CONFIG_ENCRYPTION_KEY is unavailable");
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(encryptionKey));
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, usages);
}

export async function encryptJson(value: unknown, encryptionKey: string): Promise<EncryptedBlob> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      await cryptoKey(encryptionKey, ["encrypt"]),
      encoder.encode(JSON.stringify(value)),
    ),
  );
  return { iv: bytesToBase64(iv), ciphertext: bytesToBase64(ciphertext) };
}

export async function decryptJson<T>(blob: EncryptedBlob, encryptionKey: string): Promise<T> {
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: base64ToBytes(blob.iv) },
    await cryptoKey(encryptionKey, ["decrypt"]),
    base64ToBytes(blob.ciphertext),
  );
  return JSON.parse(decoder.decode(plaintext)) as T;
}

export async function makeSensitiveAsset(input: {
  url: string;
  filename: string;
  encryptionKey: string;
  assetId?: string;
}) {
  const url = validateExportUrl(input.url);
  return {
    asset_id: input.assetId ?? "asset-1",
    provider: "openai_chatgpt_export",
    source_url_encrypted: await encryptJson(url, input.encryptionKey),
    canonical_url_encrypted: await encryptJson(url, input.encryptionKey),
    sensitive_source: true,
    filename: input.filename,
    kind: "zip",
    browser_hint: false,
    range_hint: true,
    fallback_chain: ["native"],
    state: "PENDING",
    fallback_index: 0,
    evidence: { fallback_chain: ["native"], browser_hint: false, range_hint: true },
  };
}

export async function buildMemoryExportJob(input: {
  candidate: ReturnType<typeof extractExportCandidate>;
  encryptionKey: string;
  downloadId: string;
  now?: string;
}) {
  const now = input.now ?? new Date().toISOString();
  const asset = await makeSensitiveAsset({
    url: input.candidate.url,
    filename: input.candidate.filename,
    encryptionKey: input.encryptionKey,
  });
  return {
    download_id: input.downloadId,
    request: "Download the latest OpenAI ChatGPT data export located via Gmail",
    destination: "Google Drive/Memory",
    constraints: { sensitive_source: true, preserve_signed_url_privacy: true },
    source: {
      provider: "gmail",
      gmail_message_id: input.candidate.messageId,
      received_at: new Date(input.candidate.receivedAtMs).toISOString(),
    },
    current_stage: "FETCHING",
    last_verified_stage: "RESOLVING",
    status: "FETCHING",
    assets: [asset],
    pass_files: [],
    failed_files: [],
    drive_refs: [],
    drive_verified: false,
    next_action: {
      action: "COMMIT_GITHUB_DESCRIPTOR",
      capability: "github.write",
      required: true,
      arguments: {
        repository: "QuJindai/automotive-smart-manufacturing-standards-archive",
        path: `.download/jobs/${input.downloadId}.json`,
        content: `${JSON.stringify({ download_id: input.downloadId }, null, 2)}\n`,
        message: `download: execute ${input.downloadId}`,
      },
    },
    blocker: null,
    executor: null,
    created_at: now,
    updated_at: now,
  };
}

export async function hydrateSensitiveAssets(assets: any[], encryptionKey: string): Promise<any[]> {
  return Promise.all(
    (Array.isArray(assets) ? assets : []).map(async (asset) => {
      if (asset?.sensitive_source !== true) return asset;
      if (!asset.source_url_encrypted || !asset.canonical_url_encrypted) {
        throw new Error("Sensitive download source is unavailable");
      }
      const { source_url_encrypted: _source, canonical_url_encrypted: _canonical, ...safe } = asset;
      return {
        ...safe,
        source_url: await decryptJson<string>(asset.source_url_encrypted, encryptionKey),
        canonical_url: await decryptJson<string>(asset.canonical_url_encrypted, encryptionKey),
      };
    }),
  );
}

export function redactJob<T extends Record<string, any>>(job: T): T {
  const clone = structuredClone(job);
  clone.assets = (Array.isArray(clone.assets) ? clone.assets : []).map((asset: any) => {
    if (asset?.sensitive_source !== true) return asset;
    const {
      source_url: _sourceUrl,
      canonical_url: _canonicalUrl,
      source_url_encrypted: _sourceEncrypted,
      canonical_url_encrypted: _canonicalEncrypted,
      ...redacted
    } = asset;
    return { ...redacted, source_redacted: true };
  });
  return clone;
}

export function stripSuccessfulSecrets(assets: any[], results: any[]): any[] {
  const byId = new Map(
    (Array.isArray(results) ? results : []).map((result: any) => [String(result?.asset_id ?? ""), result]),
  );
  return (Array.isArray(assets) ? assets : []).map((asset: any) => {
    const result: any = byId.get(String(asset?.asset_id ?? ""));
    if (asset?.sensitive_source !== true || result?.status !== "PASS") return asset;
    const {
      source_url: _sourceUrl,
      canonical_url: _canonicalUrl,
      source_url_encrypted: _sourceEncrypted,
      canonical_url_encrypted: _canonicalEncrypted,
      ...redacted
    } = asset;
    return { ...redacted, source_redacted: true };
  });
}
