const textEncoder = new TextEncoder();

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function pemDer(pem: string, label: "PRIVATE KEY" | "RSA PRIVATE KEY"): Uint8Array {
  const expression = new RegExp(
    `^\\s*-----BEGIN ${label}-----\\s*([A-Za-z0-9+/=\\s]+)-----END ${label}-----\\s*$`,
  );
  const match = expression.exec(pem);
  if (!match) throw new Error("invalid GitHub App private key");
  const binary = atob(match[1].replace(/\s/g, ""));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function derLength(length: number): Uint8Array {
  if (length < 128) return Uint8Array.of(length);
  const octets: number[] = [];
  for (let value = length; value > 0; value >>>= 8) octets.unshift(value & 0xff);
  return Uint8Array.of(0x80 | octets.length, ...octets);
}

function der(tag: number, value: Uint8Array): Uint8Array {
  return Uint8Array.of(tag, ...derLength(value.length), ...value);
}

function pkcs1ToPkcs8(pkcs1: Uint8Array): Uint8Array {
  const version = Uint8Array.of(0x02, 0x01, 0x00);
  const rsaEncryption = Uint8Array.of(
    0x30, 0x0d,
    0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01,
    0x05, 0x00,
  );
  return der(0x30, Uint8Array.of(...version, ...rsaEncryption, ...der(0x04, pkcs1)));
}

export async function importGitHubAppPrivateKey(
  privateKeyPem: string,
  webcrypto: Crypto = crypto,
): Promise<CryptoKey> {
  const trimmed = privateKeyPem.trim();
  const pkcs8 = trimmed.includes("-----BEGIN PRIVATE KEY-----")
    ? pemDer(trimmed, "PRIVATE KEY")
    : pkcs1ToPkcs8(pemDer(trimmed, "RSA PRIVATE KEY"));
  return webcrypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

export async function createGitHubAppJwt(input: {
  appId: string;
  privateKeyPem: string;
  nowMs: number;
  webcrypto?: Crypto;
}): Promise<string> {
  const header = base64UrlEncode(textEncoder.encode(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const nowSeconds = Math.floor(input.nowMs / 1000);
  const payload = base64UrlEncode(textEncoder.encode(JSON.stringify({
    iat: nowSeconds - 60,
    exp: nowSeconds + 540,
    iss: String(input.appId),
  })));
  const signed = `${header}.${payload}`;
  const webcrypto = input.webcrypto ?? crypto;
  const signature = await webcrypto.subtle.sign(
    { name: "RSASSA-PKCS1-v1_5" },
    await importGitHubAppPrivateKey(input.privateKeyPem, webcrypto),
    textEncoder.encode(signed),
  );
  return `${signed}.${base64UrlEncode(new Uint8Array(signature))}`;
}

export type ExecutorDispatchEvidence =
  | {
    mechanism: "github_app";
    status: "DISPATCHED";
    http_status: number;
    workflow_run_id?: number;
    run_url?: string;
  }
  | {
    mechanism: "github_app";
    status: "FALLBACK_POLLING";
    error_code: string;
    http_status?: number;
    retry_after_seconds: 300;
  };

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type Environment = Record<string, string | undefined>;
type CachedInstallationToken = { token: string; expiresAtMs: number };

class GitHubAppError extends Error {
  readonly code: string;
  readonly httpStatus?: number;

  constructor(code: string, httpStatus?: number) {
    super(code);
    this.code = code;
    this.httpStatus = httpStatus;
  }
}

function fallback(errorCode: string, httpStatus?: number): ExecutorDispatchEvidence {
  return {
    mechanism: "github_app",
    status: "FALLBACK_POLLING",
    error_code: errorCode,
    ...(httpStatus == null ? {} : { http_status: httpStatus }),
    retry_after_seconds: 300,
  };
}

export class GitHubAppDispatcher {
  private cachedInstallationToken: CachedInstallationToken | undefined;
  private readonly environment: Environment;
  private readonly owner: string;
  private readonly repository: string;
  private readonly workflow: string;
  private readonly ref: string;
  private readonly request: FetchLike;
  private readonly clock: () => number;
  private readonly webcrypto: Crypto;

  constructor(input: {
    environment: Environment;
    owner: string;
    repository: string;
    workflow: string;
    ref: string;
    fetch: FetchLike;
    now: () => number;
    webcrypto: Crypto;
  }) {
    this.environment = input.environment;
    this.owner = input.owner;
    this.repository = input.repository;
    this.workflow = input.workflow;
    this.ref = input.ref;
    this.request = input.fetch;
    this.clock = input.now;
    this.webcrypto = input.webcrypto;
  }

  async dispatch(): Promise<ExecutorDispatchEvidence> {
    try {
      let token = await this.installationToken();
      let response = await this.dispatchWith(token);
      if (response.status === 401 || response.status === 403) {
        this.cachedInstallationToken = undefined;
        token = await this.installationToken();
        response = await this.dispatchWith(token);
      }
      if (!response.ok) {
        return fallback("GITHUB_APP_WORKFLOW_DISPATCH_FAILED", response.status);
      }
      return await this.successEvidence(response);
    } catch (error) {
      if (error instanceof GitHubAppError) return fallback(error.code, error.httpStatus);
      return fallback("GITHUB_APP_DISPATCH_FAILED");
    }
  }

  private required(name: string): string {
    const value = this.environment[name]?.trim();
    if (!value) throw new GitHubAppError("GITHUB_APP_CONFIGURATION_INVALID");
    return value;
  }

  private async installationToken(): Promise<string> {
    const now = this.clock();
    if (this.cachedInstallationToken && this.cachedInstallationToken.expiresAtMs > now + 60_000) {
      return this.cachedInstallationToken.token;
    }
    const appJwt = await createGitHubAppJwt({
      appId: this.required("DOWNLOAD_GITHUB_APP_ID"),
      privateKeyPem: this.required("DOWNLOAD_GITHUB_APP_PRIVATE_KEY"),
      nowMs: now,
      webcrypto: this.webcrypto,
    });
    const installationId = this.required("DOWNLOAD_GITHUB_APP_INSTALLATION_ID");
    const response = await this.request(
      `https://api.github.com/app/installations/${encodeURIComponent(installationId)}/access_tokens`,
      {
        method: "POST",
        headers: {
          accept: "application/vnd.github+json",
          authorization: `Bearer ${appJwt}`,
          "x-github-api-version": "2022-11-28",
        },
      },
    );
    if (!response.ok) throw new GitHubAppError("GITHUB_APP_TOKEN_EXCHANGE_FAILED", response.status);
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new GitHubAppError("GITHUB_APP_TOKEN_EXCHANGE_FAILED", response.status);
    }
    const token = typeof (payload as Record<string, unknown>)?.token === "string"
      ? (payload as Record<string, string>).token
      : "";
    const expiresAtMs = Date.parse(String((payload as Record<string, unknown>)?.expires_at ?? ""));
    if (!token || !Number.isFinite(expiresAtMs)) {
      throw new GitHubAppError("GITHUB_APP_TOKEN_EXCHANGE_FAILED", response.status);
    }
    this.cachedInstallationToken = { token, expiresAtMs };
    return token;
  }

  private dispatchWith(token: string): Promise<Response> {
    return this.request(
      `https://api.github.com/repos/${encodeURIComponent(this.owner)}/${encodeURIComponent(this.repository)}` +
        `/actions/workflows/${encodeURIComponent(this.workflow)}/dispatches`,
      {
        method: "POST",
        headers: {
          accept: "application/vnd.github+json",
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
          "x-github-api-version": "2022-11-28",
        },
        body: JSON.stringify({ ref: this.ref }),
      },
    );
  }

  private async successEvidence(response: Response): Promise<ExecutorDispatchEvidence> {
    const evidence: Extract<ExecutorDispatchEvidence, { status: "DISPATCHED" }> = {
      mechanism: "github_app",
      status: "DISPATCHED",
      http_status: response.status,
    };
    if (response.status !== 200) return evidence;
    try {
      const payload = await response.json() as Record<string, unknown>;
      const runId = Number(payload.workflow_run_id ?? payload.id);
      if (Number.isSafeInteger(runId) && runId > 0) evidence.workflow_run_id = runId;
      const runUrl = payload.run_url ?? payload.html_url;
      if (typeof runUrl === "string" && runUrl) evidence.run_url = runUrl;
    } catch {
      // A successful workflow dispatch commonly has no response body.
    }
    return evidence;
  }
}

export async function dispatchAfterDurableQueue(
  job: Record<string, unknown>,
  persist: (job: Record<string, unknown>) => Promise<Record<string, unknown>>,
  dispatcher: { dispatch(): Promise<ExecutorDispatchEvidence> },
): Promise<Record<string, unknown>> {
  const persisted = await persist(job);
  if (persisted.status !== "QUEUED") return persisted;
  let evidence: ExecutorDispatchEvidence;
  try {
    evidence = await dispatcher.dispatch();
  } catch {
    evidence = fallback("GITHUB_APP_DISPATCH_FAILED");
  }
  return { ...persisted, executor_dispatch: evidence };
}
