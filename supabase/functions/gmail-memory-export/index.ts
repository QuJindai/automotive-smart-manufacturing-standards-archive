import "jsr:@supabase/functions-js/edge-runtime.d.ts";

import {
  buildMemoryExportJob,
  decryptJson,
  DRIVE_FILE_SCOPE,
  GMAIL_READONLY_SCOPE,
  hasRequiredScopes,
  OAUTH_STATE_TTL_MS,
  redactJob,
  selectLatestExportCandidate,
} from "../_shared/memory_export_core.ts";
import type { EncryptedBlob } from "../_shared/memory_export_core.ts";

const SERVICE = "gmail-memory-export";
const OWNER_ID = "00000000-0000-4000-8000-000000000091";
const AUTH_KIND = "gmail_memory_google_auth";
const DRIVE_AUTH_KIND = "download_google_auth";
const AUTH_RECORD_ID = "default";
const NOTEBOOK_CALLBACK = "https://ezvfqrhzucjvkwnnbjux.supabase.co/functions/v1/gemini-notebook-mcp-prod/oauth/callback";
const GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
const GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me";
const SUPABASE_URL = (Deno.env.get("SUPABASE_URL") ?? "").replace(/\/$/, "");
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const CONFIG_ENCRYPTION_KEY = Deno.env.get("CONFIG_ENCRYPTION_KEY") ?? "";
const CAPABILITY_SHA256 = "bd091c44cd4999f9393f18fe618e6cc7753854a1fe43ff600642c13f252645ec";
const MAX_EXPORT_AGE_MS = 24 * 60 * 60 * 1000;
const encoder = new TextEncoder();

type NotebookConfig = { google_client_id: string; google_client_secret: string };
type StoredGoogleToken = {
  access_token?: string;
  refresh_token?: string;
  expires_at?: number;
  scope?: string;
  token_type?: string;
};
type Bootstrap = {
  attempt_version: number;
  original_encrypted_token: EncryptedBlob | null;
  started_at: string;
  expires_at: string;
};
type AuthPayload = {
  authorized?: boolean;
  authorized_at?: string | null;
  scope?: string;
  redirect_strategy?: string;
  encrypted_token?: EncryptedBlob | null;
  bootstrap?: Bootstrap | null;
};
type StateRow = { payload: any; revision: number };

if (!SUPABASE_URL || !SERVICE_ROLE_KEY || CONFIG_ENCRYPTION_KEY.length < 32) {
  throw new Error("Supabase runtime configuration is unavailable");
}

const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "content-type, x-memory-export-key",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "content-type": "application/json; charset=utf-8" },
  });
}

function dbHeaders(contentType = false, prefer?: string): Record<string, string> {
  return {
    apikey: SERVICE_ROLE_KEY,
    authorization: `Bearer ${SERVICE_ROLE_KEY}`,
    accept: "application/json",
    ...(contentType ? { "content-type": "application/json" } : {}),
    ...(prefer ? { prefer } : {}),
  };
}

async function sha256Hex(value: string) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left: string, right: string) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

async function requireCapability(req: Request) {
  const supplied = req.headers.get("x-memory-export-key") ?? "";
  if (!supplied || !constantTimeEqual(await sha256Hex(supplied), CAPABILITY_SHA256)) {
    throw new Error("UNAUTHORIZED");
  }
}

function randomToken(bytes = 32) {
  const array = crypto.getRandomValues(new Uint8Array(bytes));
  let raw = "";
  for (const byte of array) raw += String.fromCharCode(byte);
  return btoa(raw).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function sameBlob(left: EncryptedBlob | null, right: EncryptedBlob | null) {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

async function readState(kind: string, recordId = AUTH_RECORD_ID): Promise<StateRow | null> {
  const query = new URLSearchParams({
    owner_id: `eq.${OWNER_ID}`,
    kind: `eq.${kind}`,
    record_id: `eq.${recordId}`,
    select: "payload,revision",
  });
  const response = await fetch(`${SUPABASE_URL}/rest/v1/iaos_mcp_state?${query}`, { headers: dbHeaders() });
  if (!response.ok) throw new Error(`State read failed: ${response.status}`);
  const rows = await response.json();
  return rows?.[0] ? { payload: rows[0].payload ?? {}, revision: Number(rows[0].revision ?? 1) } : null;
}

async function saveState(kind: string, payload: unknown, recordId = AUTH_RECORD_ID) {
  const existing = await readState(kind, recordId);
  if (existing) {
    const query = new URLSearchParams({
      owner_id: `eq.${OWNER_ID}`,
      kind: `eq.${kind}`,
      record_id: `eq.${recordId}`,
      revision: `eq.${existing.revision}`,
    });
    const response = await fetch(`${SUPABASE_URL}/rest/v1/iaos_mcp_state?${query}`, {
      method: "PATCH",
      headers: dbHeaders(true, "return=minimal"),
      body: JSON.stringify({ payload, revision: existing.revision + 1, updated_at: new Date().toISOString() }),
    });
    if (!response.ok) throw new Error(`State update failed: ${response.status}`);
    return;
  }
  const response = await fetch(`${SUPABASE_URL}/rest/v1/iaos_mcp_state`, {
    method: "POST",
    headers: dbHeaders(true, "return=minimal"),
    body: JSON.stringify({ owner_id: OWNER_ID, kind, record_id: recordId, payload, revision: 1 }),
  });
  if (!response.ok) throw new Error(`State create failed: ${response.status}`);
}

async function readNotebookConfigRow(): Promise<{
  encrypted_config: EncryptedBlob;
  encrypted_token: EncryptedBlob | null;
  oauth_attempt_version: number;
}> {
  const query = new URLSearchParams({ id: "eq.default", select: "encrypted_config,encrypted_token,oauth_attempt_version" });
  const response = await fetch(`${SUPABASE_URL}/rest/v1/gemini_notebook_connector_config?${query}`, { headers: dbHeaders() });
  if (!response.ok) throw new Error(`Notebook config read failed: ${response.status}`);
  const rows = await response.json();
  const row = rows?.[0];
  if (!row?.encrypted_config) throw new Error("Notebook Google OAuth client is not configured");
  return {
    encrypted_config: row.encrypted_config,
    encrypted_token: row.encrypted_token ?? null,
    oauth_attempt_version: Number(row.oauth_attempt_version ?? 0),
  };
}

async function beginNotebookOAuth(state: string) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/rpc/begin_gemini_notebook_oauth_attempt`, {
    method: "POST",
    headers: dbHeaders(true),
    body: JSON.stringify({ p_state_hash: await sha256Hex(state) }),
  });
  if (!response.ok) throw new Error(`OAuth state start failed: ${response.status}`);
  const data = await response.json();
  const value = Array.isArray(data) ? data[0] : data;
  const attempt = Number(value?.attempt_version ?? value ?? 0);
  if (!Number.isSafeInteger(attempt) || attempt < 1) throw new Error("OAuth attempt version missing");
  return attempt;
}

async function maybeAdopt(): Promise<AuthPayload> {
  const auth = await readState(AUTH_KIND);
  if (auth?.payload?.authorized === true && auth.payload.encrypted_token) {
    const token = await decryptJson<StoredGoogleToken>(auth.payload.encrypted_token, CONFIG_ENCRYPTION_KEY);
    if (hasRequiredScopes(token.scope)) return auth.payload;
  }

  const bootstrap: Bootstrap | null = auth?.payload?.bootstrap ?? null;
  if (!bootstrap) return auth?.payload ?? {};
  const notebook = await readNotebookConfigRow();
  const token = notebook.encrypted_token
    ? await decryptJson<StoredGoogleToken>(notebook.encrypted_token, CONFIG_ENCRYPTION_KEY)
    : null;
  const eligible =
    Boolean(token) &&
    hasRequiredScopes(token?.scope) &&
    bootstrap.attempt_version === notebook.oauth_attempt_version &&
    Date.parse(bootstrap.expires_at) > Date.now() &&
    !sameBlob(bootstrap.original_encrypted_token, notebook.encrypted_token);
  if (!eligible || !notebook.encrypted_token) return auth?.payload ?? {};

  const now = new Date().toISOString();
  const payload: AuthPayload = {
    authorized: true,
    authorized_at: now,
    scope: token?.scope ?? `${GMAIL_READONLY_SCOPE} ${DRIVE_FILE_SCOPE}`,
    redirect_strategy: "reuse-notebook-callback",
    encrypted_token: notebook.encrypted_token,
    bootstrap: null,
  };
  await saveState(AUTH_KIND, payload);
  await saveState(DRIVE_AUTH_KIND, {
    authorized: true,
    authorized_at: now,
    scope: token?.scope ?? DRIVE_FILE_SCOPE,
    redirect_strategy: "reuse-notebook-callback",
    encrypted_token: notebook.encrypted_token,
    bootstrap: null,
  });
  return payload;
}

async function oauthStart() {
  const current = await maybeAdopt();
  if (current.authorized === true && current.encrypted_token) {
    const token = await decryptJson<StoredGoogleToken>(current.encrypted_token, CONFIG_ENCRYPTION_KEY);
    if (hasRequiredScopes(token.scope)) return json({ code: "ALREADY_AUTHORIZED", authorized: true }, 409);
  }

  const auth = await readState(AUTH_KIND);
  if (auth?.payload?.bootstrap && Date.parse(auth.payload.bootstrap.expires_at) > Date.now()) {
    return json({ code: "AUTHORIZATION_IN_PROGRESS", expires_at: auth.payload.bootstrap.expires_at }, 409);
  }

  const notebook = await readNotebookConfigRow();
  const config = await decryptJson<NotebookConfig>(notebook.encrypted_config, CONFIG_ENCRYPTION_KEY);
  if (!config?.google_client_id) throw new Error("Notebook Google OAuth client ID is unavailable");
  const state = randomToken();
  const attempt = await beginNotebookOAuth(state);
  const now = Date.now();
  const expiresAt = new Date(now + OAUTH_STATE_TTL_MS).toISOString();
  await saveState(AUTH_KIND, {
    authorized: false,
    authorized_at: null,
    scope: `${GMAIL_READONLY_SCOPE} ${DRIVE_FILE_SCOPE}`,
    redirect_strategy: "reuse-notebook-callback",
    encrypted_token: null,
    bootstrap: {
      attempt_version: attempt,
      original_encrypted_token: notebook.encrypted_token,
      started_at: new Date(now).toISOString(),
      expires_at: expiresAt,
    },
  });

  const params = new URLSearchParams({
    client_id: config.google_client_id,
    redirect_uri: NOTEBOOK_CALLBACK,
    response_type: "code",
    access_type: "offline",
    prompt: "consent",
    include_granted_scopes: "true",
    state,
    scope: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/discoveryengine.readwrite",
      "https://www.googleapis.com/auth/drive.readonly",
      DRIVE_FILE_SCOPE,
      GMAIL_READONLY_SCOPE,
    ].join(" "),
  });
  return json({
    code: "AUTHORIZATION_REQUIRED",
    authorization_url: `https://accounts.google.com/o/oauth2/v2/auth?${params}`,
    expires_at: expiresAt,
    required_scopes: [GMAIL_READONLY_SCOPE, DRIVE_FILE_SCOPE],
  });
}

async function googleAccessToken() {
  const auth = await maybeAdopt();
  if (auth.authorized !== true || !auth.encrypted_token) throw new Error("AUTH_REQUIRED");
  const stored = await decryptJson<StoredGoogleToken>(auth.encrypted_token, CONFIG_ENCRYPTION_KEY);
  if (!hasRequiredScopes(stored.scope)) throw new Error("AUTH_REQUIRED");
  const expires = Number(stored.expires_at ?? 0);
  const expiresMs = expires > 10_000_000_000 ? expires : expires * 1000;
  if (stored.access_token && expiresMs > Date.now() + 60_000) return stored.access_token;
  if (!stored.refresh_token) throw new Error("Google refresh token is unavailable");

  const notebook = await readNotebookConfigRow();
  const config = await decryptJson<NotebookConfig>(notebook.encrypted_config, CONFIG_ENCRYPTION_KEY);
  const response = await fetch(GOOGLE_TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: config.google_client_id,
      client_secret: config.google_client_secret,
      refresh_token: stored.refresh_token,
      grant_type: "refresh_token",
    }),
  });
  if (!response.ok) throw new Error(`Google token refresh failed: ${response.status}`);
  const token = await response.json();
  if (!token?.access_token) throw new Error("Google token refresh returned no access token");
  return String(token.access_token);
}

async function gmailFetch(path: string) {
  const token = await googleAccessToken();
  const response = await fetch(`${GMAIL_API}${path}`, {
    headers: { authorization: `Bearer ${token}`, accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`Gmail API request failed: ${response.status}`);
  return response.json();
}

async function latestExportCandidate() {
  const query = new URLSearchParams({
    q: "from:noreply@tm.openai.com newer_than:180d",
    maxResults: "25",
    includeSpamTrash: "false",
  });
  const listed = await gmailFetch(`/messages?${query}`);
  const ids = (Array.isArray(listed?.messages) ? listed.messages : [])
    .map((message: any) => String(message?.id ?? ""))
    .filter(Boolean);
  if (!ids.length) throw new Error("No recent OpenAI email was found in Gmail");
  const messages = await Promise.all(
    ids.map((id: string) => gmailFetch(`/messages/${encodeURIComponent(id)}?format=full`)),
  );
  return selectLatestExportCandidate(messages);
}

async function readDownloadJob(downloadId: string) {
  return readState("download_job", downloadId);
}

async function createDownloadJob(job: any) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/iaos_mcp_state`, {
    method: "POST",
    headers: dbHeaders(true, "return=minimal"),
    body: JSON.stringify({
      owner_id: OWNER_ID,
      kind: "download_job",
      record_id: job.download_id,
      payload: job,
      revision: 1,
    }),
  });
  if (!response.ok) throw new Error(`Download state create failed: ${response.status}`);
}

function jobSummary(job: any, disposition: "created" | "reused") {
  const safe = redactJob(job);
  return {
    disposition,
    download_id: safe.download_id,
    status: safe.status,
    filename: safe.assets?.[0]?.filename ?? null,
    gmail_message_id: safe.source?.gmail_message_id ?? null,
    received_at: safe.source?.received_at ?? null,
    descriptor: safe.next_action?.action === "COMMIT_GITHUB_DESCRIPTOR" ? safe.next_action.arguments : null,
  };
}

async function queueLatestExport() {
  const candidate = await latestExportCandidate();
  if (Date.now() - candidate.receivedAtMs > MAX_EXPORT_AGE_MS) {
    return json({
      code: "EXPORT_LINK_STALE",
      message: "The newest OpenAI export email is older than 24 hours; request a fresh ChatGPT data export.",
      gmail_message_id: candidate.messageId,
      received_at: new Date(candidate.receivedAtMs).toISOString(),
    }, 409);
  }

  const messageHash = await sha256Hex(candidate.messageId);
  const downloadId = `download-memory-${messageHash.slice(0, 24)}`;
  const existing = await readDownloadJob(downloadId);
  if (existing?.payload) return json(jobSummary(existing.payload, "reused"));

  const job = await buildMemoryExportJob({
    candidate,
    encryptionKey: CONFIG_ENCRYPTION_KEY,
    downloadId,
  });
  await createDownloadJob(job);
  return json(jobSummary(job, "created"));
}

function safeMessage(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/https:\/\/[^\s"']+/gi, "[redacted-url]");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  const url = new URL(req.url);
  const marker = `/${SERVICE}`;
  const sub = url.pathname.includes(marker)
    ? url.pathname.slice(url.pathname.indexOf(marker) + marker.length) || "/"
    : "/";

  if (req.method === "GET" && sub === "/health") {
    return json({ status: "ok", service: SERVICE, auth: "capability-header", scopes: [GMAIL_READONLY_SCOPE] });
  }

  try {
    await requireCapability(req);
    if (req.method === "POST" && sub === "/oauth/start") return await oauthStart();
    if (req.method === "GET" && sub === "/oauth/status") {
      const auth = await maybeAdopt();
      const token = auth.encrypted_token
        ? await decryptJson<StoredGoogleToken>(auth.encrypted_token, CONFIG_ENCRYPTION_KEY)
        : null;
      return json({
        service: SERVICE,
        authorized: auth.authorized === true && hasRequiredScopes(token?.scope),
        authorized_at: auth.authorized_at ?? null,
        required_scopes: [GMAIL_READONLY_SCOPE, DRIVE_FILE_SCOPE],
      });
    }
    if (req.method === "POST" && sub === "/queue-latest") return await queueLatestExport();
    return json({ error: "not_found" }, 404);
  } catch (error) {
    const message = safeMessage(error);
    if (message === "UNAUTHORIZED") return json({ error: "unauthorized" }, 401);
    if (message === "AUTH_REQUIRED") return json({ code: "AUTH_REQUIRED" }, 409);
    return json({ code: "MEMORY_EXPORT_ERROR", message }, 500);
  }
});
